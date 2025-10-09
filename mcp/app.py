# mcp/app.py
import os
import time
import uuid
import json
import threading
import sqlite3
from typing import List
from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv
import requests
import faiss
import numpy as np

from utils import ensure_dir, extract_text_from_pdf, chunk_text, safe_write_json, safe_read_json

load_dotenv()

APP = Flask(__name__)

# Configuration
DATA_DIR = os.getenv("MCP_DATA_DIR", "../data/mcp")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
INDEX_DIR = os.path.join(DATA_DIR, "faiss")
META_PATH = os.path.join(DATA_DIR, "metadata.json")
STATUS_DB = os.path.join(DATA_DIR, "status.sqlite")
LLM_EMBED_ENDPOINT = os.getenv("LLM_EMBED_ENDPOINT", "http://127.0.0.1:5000/embed")
LLM_TEXT_ENDPOINT = os.getenv("LLM_TEXT_ENDPOINT", "http://127.0.0.1:5000/query")
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "64"))
EMBED_DIM = int(os.getenv("EMBED_DIM", "1536"))  # guess — will adapt if embedding returns different dim

ensure_dir(DATA_DIR)
ensure_dir(UPLOADS_DIR)
ensure_dir(INDEX_DIR)

# metadata.json keeps a mapping of vector-id -> metadata
metadata = safe_read_json(META_PATH, default={})
# We'll keep ID ordering in metadata list form for easy mapping
# metadata structure: { "vectors": { "<vec_id>": {meta...}}, "index_id_list": ["<vec_id>", ...] }
if "vectors" not in metadata:
    metadata["vectors"] = {}
if "index_id_list" not in metadata:
    metadata["index_id_list"] = []

# FAISS index (L2 normalized). We'll create an IndexFlatIP (inner product) after normalizing embeddings.
index_path = os.path.join(INDEX_DIR, "faiss.index")
_index = None

def init_faiss(dim: int):
    global _index, EMBED_DIM
    EMBED_DIM = dim
    if os.path.exists(index_path):
        try:
            _index = faiss.read_index(index_path)
            print("[mcp] Loaded existing FAISS index.")
            return
        except Exception as e:
            print("[mcp] Failed to load existing index:", e)
    # create new index (inner product on normalized vectors approximates cosine)
    quant = faiss.IndexFlatIP(dim)
    _index = quant
    print("[mcp] New FAISS index created with dim", dim)

# Simple sqlite status DB (upload_id -> status info)
def init_status_db():
    conn = sqlite3.connect(STATUS_DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            upload_id TEXT PRIMARY KEY,
            filename TEXT,
            title TEXT,
            author TEXT,
            user_id TEXT,
            status TEXT,
            created_at REAL,
            processed_chunks INTEGER,
            total_chunks INTEGER,
            error TEXT
        )
    """)
    conn.commit()
    conn.close()

init_status_db()
# initialize index with guessed dimension — may be re-initialised after first embed call
init_faiss(EMBED_DIM)

# ----------------- Status helpers -----------------
def set_status_row(upload_id, **kwargs):
    conn = sqlite3.connect(STATUS_DB)
    cur = conn.cursor()
    # upsert
    cur.execute("SELECT upload_id FROM uploads WHERE upload_id = ?", (upload_id,))
    if cur.fetchone():
        # update
        sets = ", ".join([f"{k}=?" for k in kwargs.keys()])
        vals = list(kwargs.values())
        vals.append(upload_id)
        cur.execute(f"UPDATE uploads SET {sets} WHERE upload_id = ?", vals)
    else:
        # need minimal row
        now = time.time()
        cur.execute("""
            INSERT INTO uploads (upload_id, filename, title, author, user_id, status, created_at, processed_chunks, total_chunks, error)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            upload_id,
            kwargs.get("filename"),
            kwargs.get("title"),
            kwargs.get("author"),
            kwargs.get("user_id"),
            kwargs.get("status", "created"),
            now,
            kwargs.get("processed_chunks", 0),
            kwargs.get("total_chunks", 0),
            kwargs.get("error")
        ))
    conn.commit()
    conn.close()

def get_status_row(upload_id):
    conn = sqlite3.connect(STATUS_DB)
    cur = conn.cursor()
    cur.execute("SELECT upload_id, filename, title, author, user_id, status, created_at, processed_chunks, total_chunks, error FROM uploads WHERE upload_id = ?", (upload_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    keys = ["upload_id","filename","title","author","user_id","status","created_at","processed_chunks","total_chunks","error"]
    return dict(zip(keys,row))

# ----------------- Embedding helpers -----------------
def call_llm_embed(texts: List[str]):
    """
    Post to your LLM embed endpoint.
    Expects JSON { "texts": [...] } and returns {"embeddings":[ [..], [...]]}
    """
    try:
        payload = {"texts": texts}
        r = requests.post(LLM_EMBED_ENDPOINT, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        embs = data.get("embeddings")
        if not embs:
            raise ValueError("No embeddings returned")
        return embs
    except Exception as e:
        raise

def normalize_vectors(vs: np.ndarray):
    """
    Normalize each vector to unit length for cosine-sim via inner product search.
    vs: ndarray (n, dim)
    """
    norms = np.linalg.norm(vs, axis=1, keepdims=True)
    norms[norms==0] = 1.0
    return vs / norms

def add_vectors_to_index(vec_ids: List[str], vectors: List[List[float]], metadatas: List[dict]):
    """
    Adds vectors to FAISS and updates metadata mapping
    """
    global _index
    vecs_np = np.array(vectors, dtype=np.float32)
    # adjust dim if needed
    if vecs_np.shape[1] != EMBED_DIM:
        # reinit index with new dim (if index empty) OR raise if not empty
        if len(metadata["index_id_list"]) == 0:
            init_faiss(vecs_np.shape[1])
        else:
            raise RuntimeError(f"Embedding dimension mismatch: index dim {EMBED_DIM} vs vec dim {vecs_np.shape[1]}")

    vecs_np = normalize_vectors(vecs_np)  # normalize before IndexFlatIP
    # add to index
    _index.add(vecs_np)
    # record metadata mapping; index_id_list maintains insertion order
    for vid, meta in zip(vec_ids, metadatas):
        metadata["index_id_list"].append(vid)
        metadata["vectors"][vid] = meta
    safe_write_json(META_PATH, metadata)
    # persist index
    faiss.write_index(_index, index_path)

# ----------------- Background processing -----------------
def process_upload(upload_id, file_path, title, author, user_id):
    """
    Steps:
    1. Extract text
    2. Chunk
    3. Embed in batches
    4. Add to FAISS + metadata
    Updates upload status row during processing
    """
    try:
        set_status_row(upload_id, status="processing", filename=os.path.basename(file_path), title=title, author=author, user_id=user_id, processed_chunks=0, total_chunks=0)
        text = extract_text_from_pdf(file_path)
        if not text.strip():
            set_status_row(upload_id, status="error", error="No text extracted from PDF")
            return

        chunks = chunk_text(text, chunk_size_chars=1200, overlap_chars=200)
        total = len(chunks)
        set_status_row(upload_id, status="embedding", processed_chunks=0, total_chunks=total)
        # prepare batched embedding calls
        batch_size = EMBED_BATCH
        all_vec_ids = []
        all_vectors = []
        all_metas = []
        for i in range(0, total, batch_size):
            batch = chunks[i:i+batch_size]
            texts = [c["text"] for c in batch]
            # call LLM embed
            try:
                embs = call_llm_embed(texts)
            except Exception as e:
                set_status_row(upload_id, status="error", error=f"Embed call failed: {e}")
                return

            # ensure embs is list of lists
            if not isinstance(embs, list) or not embs:
                set_status_row(upload_id, status="error", error="Invalid embeddings returned")
                return

            for c, emb in zip(batch, embs):
                vid = c["id"]
                meta = {
                    "upload_id": upload_id,
                    "title": title,
                    "author": author,
                    "user_id": user_id,
                    "text": c["text"],
                    "start": c["start"],
                    "end": c["end"],
                    "filename": os.path.basename(file_path),
                    "created_at": time.time()
                }
                all_vec_ids.append(vid)
                all_vectors.append(emb)
                all_metas.append(meta)

            # after each batch, add to index for persistence and update status
            add_vectors_to_index(all_vec_ids, all_vectors, all_metas)
            all_vec_ids.clear()
            all_vectors.clear()
            all_metas.clear()
            processed = min(i + batch_size, total)
            set_status_row(upload_id, status="indexed", processed_chunks=processed, total_chunks=total)

        set_status_row(upload_id, status="done", processed_chunks=total, total_chunks=total)
    except Exception as e:
        set_status_row(upload_id, status="error", error=str(e))

# ----------------- Routes -----------------
@APP.route("/mcp/upload", methods=["POST"])
def upload():
    """
    Accept file upload (multipart/form-data):
    Fields: pdf (file), user_id, title, author, book_id (optional)
    """
    f = request.files.get("pdf")
    user_id = request.form.get("user_id")
    title = request.form.get("title") or ""
    author = request.form.get("author") or ""
    book_id = request.form.get("book_id")

    if not f or not user_id or not title or not author:
        return jsonify({"error": "Missing required fields: pdf, user_id, title, author"}), 400

    upload_id = str(uuid.uuid4())
    filename = f"{upload_id}_{f.filename}"
    path = os.path.join(UPLOADS_DIR, filename)
    f.save(path)

    # record initial status
    set_status_row(upload_id, filename=filename, title=title, author=author, user_id=user_id, status="uploaded", processed_chunks=0, total_chunks=0)

    # start background thread to process upload
    t = threading.Thread(target=process_upload, args=(upload_id, path, title, author, user_id), daemon=True)
    t.start()

    return jsonify({"upload_id": upload_id, "status": "started"})

@APP.route("/mcp/status/<upload_id>", methods=["GET"])
def status(upload_id):
    row = get_status_row(upload_id)
    if not row:
        return jsonify({"error": "upload_id not found"}), 404
    # also include any metrics (e.g., total vectors)
    total_vectors = len(metadata.get("index_id_list", []))
    row["total_vectors"] = total_vectors
    return jsonify(row)

@APP.route("/mcp/search", methods=["POST"])
def search():
    """
    Request JSON: { "query": "<text>", "user_id": "..." , "top_k": 5 }
    Returns: { "answer": "...", "results": [ {score, metadata} ... ] }
    """
    body = request.get_json(force=True)
    query = (body.get("query") or "").strip()
    user_id = body.get("user_id")
    top_k = int(body.get("top_k", 5))

    if not query:
        return jsonify({"error": "Empty query"}), 400

    # 1) get query embedding
    try:
        q_embs = call_llm_embed([query])  # returns list with one embedding
    except Exception as e:
        return jsonify({"error": f"Embed call failed: {e}"}), 500

    if not q_embs or not isinstance(q_embs, list):
        return jsonify({"error": "Invalid embedding response"}), 500

    q_vec = np.array(q_embs, dtype=np.float32)
    if q_vec.shape[1] != EMBED_DIM:
        # if index empty, re-init index with this dim
        if len(metadata["index_id_list"]) == 0:
            init_faiss(q_vec.shape[1])
        else:
            return jsonify({"error": f"Query embedding dim mismatch: {q_vec.shape[1]} != {EMBED_DIM}"}), 500

    # normalize
    q_vec = q_vec / np.linalg.norm(q_vec, axis=1, keepdims=True)

    # 2) search FAISS
    if _index is None or _index.ntotal == 0:
        return jsonify({"answer": "No indexed documents available yet.", "results": []})

    D, I = _index.search(q_vec, top_k)
    scores = D[0].tolist()
    idxs = I[0].tolist()

    results = []
    for score, idx in zip(scores, idxs):
        if idx < 0:
            continue
        try:
            vid = metadata["index_id_list"][idx]
            meta = metadata["vectors"].get(vid, {})
            results.append({
                "vector_id": vid,
                "score": float(score),
                "meta": meta
            })
        except Exception:
            continue

    # 3) Build RAG prompt with top chunks and call LLM text generation
    # Create a short context of top 4 results
    context_texts = []
    for r in results[:4]:
        m = r["meta"]
        context_texts.append(f"TITLE: {m.get('title')}\nAUTHOR: {m.get('author')}\nTEXT_SNIPPET: {m.get('text')}\n---")

    rag_prompt = (
        "You are BookShelf-AI. Use the following document snippets from our library to answer the user's question. "
        "Do not hallucinate: if the answer is not present in the snippets, say you don't know.\n\n"
        f"CONTEXT SNIPPETS:\n{chr(10).join(context_texts)}\n\nUser question: {query}\n\nAnswer concisely and mention which snippet(s) you used (by title or upload_id) if relevant."
    )

    try:
        r = requests.post(LLM_TEXT_ENDPOINT, json={"prompt": rag_prompt, "mode": "text"}, timeout=30)
        r.raise_for_status()
        answer_text = (r.json().get("text") or "").strip()
    except Exception as e:
        # fallback: return snippets only
        answer_text = "Failed to call LLM for final answer. Returning retrieved snippets."

    return jsonify({"answer": answer_text, "results": results})

# Health
@APP.route("/mcp/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "indexed_vectors": len(metadata.get("index_id_list", []))})

if __name__ == "__main__":
    print("[mcp] Starting MCP service on port 8001")
    APP.run(host="0.0.0.0", port=8001, debug=True)
