import os
import time
import uuid
import json
import threading
import sqlite3
import traceback
from typing import List, Optional
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
import requests
import faiss
import numpy as np

# local utils expected in same package
from utils import ensure_dir, extract_text_from_pdf, chunk_text, safe_write_json, safe_read_json

load_dotenv()

APP = Flask(__name__)
CORS(APP)

# --------- Configuration ----------
DATA_DIR = os.getenv("MCP_DATA_DIR", "../data/mcp")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
INDEX_DIR = os.path.join(DATA_DIR, "faiss")
META_PATH = os.path.join(DATA_DIR, "metadata.json")
STATUS_DB = os.path.join(DATA_DIR, "status.sqlite")
LLM_EMBED_ENDPOINT = os.getenv("LLM_EMBED_ENDPOINT", "http://127.0.0.1:5000/embed")
LLM_TEXT_ENDPOINT = os.getenv("LLM_TEXT_ENDPOINT", "http://127.0.0.1:5000/query")
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "64"))
# If EMBED_DIM env is provided it will set a suggested default. Real dim validated on first embed.
EMBED_DIM = int(os.getenv("EMBED_DIM", "0"))

ensure_dir(DATA_DIR)
ensure_dir(UPLOADS_DIR)
ensure_dir(INDEX_DIR)

# metadata.json keeps a mapping of vector-id -> metadata
metadata = safe_read_json(META_PATH, default={})
metadata.setdefault("vectors", {})
metadata.setdefault("index_id_list", [])
metadata.setdefault("books", {})
# store embed_dim in metadata if present
if "embed_dim" not in metadata:
    if EMBED_DIM and EMBED_DIM > 0:
        metadata["embed_dim"] = EMBED_DIM
    else:
        metadata["embed_dim"] = 0
else:
    try:
        EMBED_DIM = int(metadata.get("embed_dim", EMBED_DIM))
    except Exception:
        pass
metadata.setdefault("next_int_id", 1)

# FAISS index object and index path
index_path = os.path.join(INDEX_DIR, "faiss.index")
_index: Optional[faiss.Index] = None

def init_faiss(dim: int):
    """
    Initialize the global FAISS index object. If an index file exists try to load it
    (and validate dim), otherwise create a new IndexFlatIP with given dim.
    """
    global _index, EMBED_DIM
    EMBED_DIM = int(dim)
    # try load existing index if present
    if os.path.exists(index_path):
        try:
            _index = faiss.read_index(index_path)
            print(f"[mcp] Loaded existing FAISS index from {index_path} (dim {EMBED_DIM}).")
            return
        except Exception as e:
            print("[mcp] Failed to load existing FAISS index, will recreate. Error:", e)

    # create new index (IndexFlatIP expects normalized vectors for cosine-like search)
    _index = faiss.IndexFlatIP(EMBED_DIM)
    print(f"[mcp] Created new FAISS IndexFlatIP with dim={EMBED_DIM}.")

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

# If EMBED_DIM was recorded in metadata use that; else if env provided use env; else leave 0 until first embed
if metadata.get("embed_dim", 0):
    EMBED_DIM = int(metadata["embed_dim"])
if EMBED_DIM and EMBED_DIM > 0:
    init_faiss(EMBED_DIM)
else:
    # create a tiny placeholder index until we know the dimension (will be reinitialized later)
    print("[mcp] EMBED_DIM unknown at startup; FAISS will be initialized upon first embeddings.")

# ----------------- Status helpers -----------------
def set_status_row(upload_id, **kwargs):
    conn = sqlite3.connect(STATUS_DB)
    cur = conn.cursor()
    cur.execute("SELECT upload_id FROM uploads WHERE upload_id = ?", (upload_id,))
    exists = cur.fetchone() is not None
    if exists:
        sets = ", ".join([f"{k}=?" for k in kwargs.keys()])
        vals = list(kwargs.values())
        vals.append(upload_id)
        cur.execute(f"UPDATE uploads SET {sets} WHERE upload_id = ?", vals)
    else:
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
def _extract_embeddings_from_llm_response(resp_json):
    """
    Extract embeddings from various JSON shapes returned by LLM embed endpoints.
    Returns list-of-lists (embeddings).
    """
    if not isinstance(resp_json, dict):
        raise ValueError("LLM embed response is not a JSON object")

    # direct "embeddings": [[...], ...]
    if "embeddings" in resp_json:
        val = resp_json["embeddings"]
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            # nested shapes
            if "embedding" in val and isinstance(val["embedding"], list):
                return val["embedding"]
            if "data" in val and isinstance(val["data"], list):
                out = []
                for item in val["data"]:
                    if isinstance(item, dict) and "embedding" in item:
                        out.append(item["embedding"])
                    elif isinstance(item, dict) and "vector" in item:
                        out.append(item["vector"])
                if out:
                    return out

    # single "embedding"
    if "embedding" in resp_json and isinstance(resp_json["embedding"], list):
        return [resp_json["embedding"]]

    # openai-like "data": [{embedding: [...]}, ...]
    if "data" in resp_json and isinstance(resp_json["data"], list):
        out = []
        for item in resp_json["data"]:
            if isinstance(item, dict):
                if "embedding" in item and isinstance(item["embedding"], list):
                    out.append(item["embedding"])
                elif "vector" in item and isinstance(item["vector"], list):
                    out.append(item["vector"])
        if out:
            return out

    # nested "result" or other wrappers
    if "result" in resp_json and isinstance(resp_json["result"], dict):
        return _extract_embeddings_from_llm_response(resp_json["result"])

    # recursive search fallback
    def find_list_of_number_lists(obj):
        if isinstance(obj, list):
            if all(isinstance(el, (list, tuple)) for el in obj) and len(obj) > 0 and all(all(isinstance(x, (int, float)) for x in el) for el in obj):
                return obj
            for el in obj:
                f = find_list_of_number_lists(el)
                if f:
                    return f
        elif isinstance(obj, dict):
            for v in obj.values():
                f = find_list_of_number_lists(v)
                if f:
                    return f
        return None

    found = find_list_of_number_lists(resp_json)
    if found:
        return found

    raise ValueError("Couldn't find embeddings in LLM response (unexpected JSON shape)")

def call_llm_embed(texts: List[str]) -> List[List[float]]:
    """
    Call the configured LLM embedding endpoint with JSON {"texts": [...]}
    and return list-of-list embeddings. Raises on failure.
    """
    payload = {"texts": texts}
    try:
        resp = requests.post(LLM_EMBED_ENDPOINT, json=payload, timeout=60)
    except Exception as e:
        raise RuntimeError(f"HTTP call to embed endpoint failed: {e}")

    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"Embed endpoint returned non-JSON: {resp.text[:1000]} (status {resp.status_code})")

    # extract embeddings
    embs = _extract_embeddings_from_llm_response(data)
    if not isinstance(embs, list) or len(embs) == 0:
        raise RuntimeError("No embeddings parsed from LLM response")

    # validate numeric and consistent dims
    first_len = None
    for i, e in enumerate(embs):
        if not isinstance(e, (list, tuple)):
            raise RuntimeError(f"Embedding {i} is not a list")
        if len(e) == 0:
            raise RuntimeError(f"Embedding {i} is empty")
        if not all(isinstance(x, (int, float)) for x in e):
            raise RuntimeError(f"Embedding {i} contains non-numeric values")
        if first_len is None:
            first_len = len(e)
        elif len(e) != first_len:
            raise RuntimeError("Inconsistent embedding lengths in LLM response")
    return embs

def normalize_vectors(vs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vs / norms

def add_vectors_to_index(vec_ids: List[str], vectors: List[List[float]], metadatas: List[dict]):
    """
    Add vectors to FAISS index, update metadata, and persist index+metadata.
    This function will create/re-init the FAISS index if embed dim differs and index is empty.
    """
    global _index, EMBED_DIM, metadata  # <<< ensure we refer to module-level variables
    if len(vectors) == 0:
        return

    vecs_np = np.array(vectors, dtype=np.float32)
    vec_dim = vecs_np.shape[1]

    # If we didn't know EMBED_DIM yet, attempt to set it and init index
    if not EMBED_DIM or EMBED_DIM == 0:
        init_faiss(vec_dim)
        EMBED_DIM = vec_dim
        metadata["embed_dim"] = EMBED_DIM
        safe_write_json(META_PATH, metadata)

    if vec_dim != EMBED_DIM:
        # if index has no vectors, we can re-init; otherwise that's an error
        if len(metadata.get("index_id_list", [])) == 0:
            init_faiss(vec_dim)
            EMBED_DIM = vec_dim
            metadata["embed_dim"] = EMBED_DIM
            safe_write_json(META_PATH, metadata)
        else:
            raise RuntimeError(f"Embedding dimension mismatch: index dim {EMBED_DIM} vs vec dim {vec_dim}")

    # normalize, add to index
    vecs_np = normalize_vectors(vecs_np)
    if _index is None:
        init_faiss(EMBED_DIM)
    try:
        _index.add(vecs_np)
    except Exception as e:
        raise RuntimeError(f"FAISS add failed: {e}")

    # persist metadata and embedding copies for rebuilds
    for vid, meta, emb in zip(vec_ids, metadatas, vectors):
        metadata["index_id_list"].append(vid)
        metadata["vectors"][vid] = meta.copy()
        # store embedding for rebuild
        metadata["vectors"][vid]["embedding"] = [float(x) for x in emb]
        # link to book registry
        book_id = meta.get("book_id")
        if book_id:
            b = metadata.setdefault("books", {}).setdefault(book_id, {
                "title": meta.get("title", ""),
                "author": meta.get("author", ""),
                "genre": "",
                "filename": meta.get("filename", ""),
                "upload_id": meta.get("upload_id"),
                "vector_ids": [],
                "created_at": time.time()
            })
            if vid not in b.get("vector_ids", []):
                b.setdefault("vector_ids", []).append(vid)

    safe_write_json(META_PATH, metadata)
    # persist FAISS
    try:
        faiss.write_index(_index, index_path)
    except Exception as e:
        print("[mcp] Warning: failed to write FAISS index to disk:", e)

# ----------------- Background processing -----------------
def process_upload(upload_id, file_path, title, author, user_id, book_id=None, genre=""):
    """
    Background worker:
     - extract text
     - chunk
     - embed in batches
     - add to index + metadata
    """
    try:
        set_status_row(upload_id, status="processing", filename=os.path.basename(file_path), title=title, author=author, user_id=user_id, processed_chunks=0, total_chunks=0)
        text = extract_text_from_pdf(file_path)
        if not text or not text.strip():
            set_status_row(upload_id, status="error", error="No text extracted from PDF")
            return

        # chunk_text should accept book_id for per-chunk metadata propagation
        chunks = chunk_text(text, chunk_size_chars=1200, overlap_chars=200, book_id=book_id)
        total = len(chunks)
        if total == 0:
            set_status_row(upload_id, status="error", error="No chunks produced from document")
            return

        # prepare book registry entry WITH GENRE
        if book_id:
            metadata.setdefault("books", {})
            if book_id not in metadata["books"]:
                metadata["books"][book_id] = {
                    "title": title,
                    "author": author,
                    "genre": genre,  # NEW: Store genre
                    "filename": os.path.basename(file_path),
                    "upload_id": upload_id,
                    "vector_ids": [],
                    "created_at": time.time()
                }
                safe_write_json(META_PATH, metadata)

        set_status_row(upload_id, status="embedding", processed_chunks=0, total_chunks=total)

        # batching
        batch_size = EMBED_BATCH if EMBED_BATCH and EMBED_BATCH > 0 else 32
        for i in range(0, total, batch_size):
            batch = chunks[i:i+batch_size]
            texts = [c["text"] for c in batch]
            try:
                embs = call_llm_embed(texts)
            except Exception as e:
                set_status_row(upload_id, status="error", error=f"Embed call failed: {e}")
                return

            # prepare metadata and ids for this batch
            vec_ids = []
            vecs = []
            metas = []
            for c, emb in zip(batch, embs):
                vid = c["id"]
                meta = {
                    "upload_id": upload_id,
                    "book_id": book_id,
                    "title": title,
                    "author": author,
                    "genre": genre,  # NEW: Include genre in vector metadata
                    "user_id": user_id,
                    "text": c["text"],
                    "start": c.get("start"),
                    "end": c.get("end"),
                    "filename": os.path.basename(file_path),
                    "created_at": time.time()
                }
                vec_ids.append(vid)
                vecs.append(emb)
                metas.append(meta)

            # add to index and persist after each batch
            add_vectors_to_index(vec_ids, vecs, metas)

            processed = min(i + batch_size, total)
            set_status_row(upload_id, status="indexed", processed_chunks=processed, total_chunks=total)

        set_status_row(upload_id, status="done", processed_chunks=total, total_chunks=total)
    except Exception as e:
        tb = traceback.format_exc()
        print("[mcp] process_upload ERROR:", e)
        print(tb)
        set_status_row(upload_id, status="error", error=str(e))

# ----------------- Routes -----------------
@APP.route("/mcp/upload", methods=["POST"])
def upload():
    f = request.files.get("pdf")
    user_id = request.form.get("user_id")
    title = request.form.get("title") or ""
    author = request.form.get("author") or ""
    genre = request.form.get("genre") or ""  # NEW: Added genre
    book_id = request.form.get("book_id")

    if not f or not user_id or not title or not author:
        return jsonify({"error": "Missing required fields: pdf, user_id, title, author"}), 400

    upload_id = str(uuid.uuid4())
    filename = f"{upload_id}_{f.filename}"
    path = os.path.join(UPLOADS_DIR, filename)
    f.save(path)

    set_status_row(upload_id, filename=filename, title=title, author=author, user_id=user_id, status="uploaded", processed_chunks=0, total_chunks=0)

    # Pass genre to background processor
    t = threading.Thread(target=process_upload, args=(upload_id, path, title, author, user_id, book_id, genre), daemon=True)
    t.start()

    return jsonify({"upload_id": upload_id, "status": "started"})

@APP.route("/mcp/status/<upload_id>", methods=["GET"])
def status(upload_id):
    row = get_status_row(upload_id)
    if not row:
        return jsonify({"error": "upload_id not found"}), 404
    total_vectors = len(metadata.get("index_id_list", []))
    row["total_vectors"] = total_vectors
    return jsonify(row)

@APP.route("/mcp/search", methods=["POST"])
def search():
    global EMBED_DIM, _index, metadata  # <<< declare globals since we assign to EMBED_DIM below
    body = request.get_json(force=True) or {}
    query = (body.get("query") or "").strip()
    user_id = body.get("user_id")
    top_k = int(body.get("top_k", 5))

    if not query:
        return jsonify({"error": "Empty query"}), 400
    
    if query.lower() in ["hey", "hi", "hello", "hola", "yo", "hey there", "how are you", "what's up"]:
        return jsonify({
        "answer": "Hey there! 👋 I'm BookShelf-AI — your personal library assistant. You can ask me about any book or topic from the library.",
        "results": []
    })
    
    # 1) embed the query
    try:
        q_embs = call_llm_embed([query])
    except Exception as e:
        return jsonify({"error": f"Embed call failed: {e}"}), 500

    if not q_embs or not isinstance(q_embs, list):
        return jsonify({"error": "Invalid embedding response"}), 500

    q_vec = np.array(q_embs, dtype=np.float32)
    if q_vec.ndim == 1:
        q_vec = q_vec.reshape(1, -1)

    # dimension checks and potential re-init
    if metadata.get("embed_dim", 0) == 0 and q_vec.shape[1] > 0:
        # If no index vectors yet, set embed_dim to this model's dim
        if len(metadata.get("index_id_list", [])) == 0:
            init_faiss(q_vec.shape[1])
            EMBED_DIM = q_vec.shape[1]
            metadata["embed_dim"] = EMBED_DIM
            safe_write_json(META_PATH, metadata)
        else:
            return jsonify({"error": "Unknown stored embed dim; please rebuild index or set EMBED_DIM"}), 500

    if q_vec.shape[1] != metadata.get("embed_dim", EMBED_DIM):
        # If index empty allow reinit
        if len(metadata.get("index_id_list", [])) == 0:
            init_faiss(q_vec.shape[1])
            metadata["embed_dim"] = q_vec.shape[1]
            safe_write_json(META_PATH, metadata)
            EMBED_DIM = q_vec.shape[1]
        else:
            return jsonify({"error": f"Query embedding dim mismatch: returned {q_vec.shape[1]} != expected {metadata.get('embed_dim')}. If you changed embedding model rebuild index."}), 500

    # normalize query vector
    q_vec = normalize_vectors(q_vec)

    # no vectors yet
    if _index is None or getattr(_index, "ntotal", 0) == 0:
        return jsonify({"answer": "No indexed documents available yet.", "results": []})

    try:
        D, I = _index.search(q_vec, top_k)
    except Exception as e:
        return jsonify({"error": f"FAISS search failed: {e}"}), 500

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

    # Build RAG prompt (intentionally kept permissive for your project)
    context_texts = []
    for r in results[:4]:
        m = r["meta"]
        context_texts.append(f"TITLE: {m.get('title')}\nAUTHOR: {m.get('author')}\nTEXT_SNIPPET: {m.get('text')}\n---")

    rag_prompt = (
        "You are BookShelf-AI. Use the following document snippets from our library to answer the user's question. "
        "Do not hallucinate: if the answer is not present in the snippets, say you don't know.\n\n"
        f"CONTEXT SNIPPETS:\n{chr(10).join(context_texts)}\n\nUser question: {query}\n\nAnswer concisely and mention which snippet(s) you used (by title or upload_id) if relevant."
    )

    answer_text = ""
    try:
        r = requests.post(LLM_TEXT_ENDPOINT, json={"prompt": rag_prompt, "mode": "text"}, timeout=30)
        r.raise_for_status()
        answer_text = (r.json().get("text") or "").strip()
    except Exception as e:
        # fallback: return snippets only
        print("[mcp] Warning: LLM text call failed:", e)
        answer_text = "Failed to call LLM for final answer. Returning retrieved snippets."

    return jsonify({"answer": answer_text, "results": results})


# Book-level endpoints
@APP.route("/mcp/list_books", methods=["GET"])
def list_books():
    books = []
    for bid, b in metadata.get("books", {}).items():
        books.append({
            "book_id": bid,
            "title": b.get("title"),
            "author": b.get("author"),
            "genre": b.get("genre"),
            "filename": b.get("filename"),
            "upload_id": b.get("upload_id"),
            "vector_count": len(b.get("vector_ids", [])),
            "created_at": b.get("created_at")
        })
    return jsonify({"books": books})

@APP.route("/mcp/get_book/<book_id>", methods=["GET"])
def get_book(book_id):
    b = metadata.get("books", {}).get(book_id)
    if not b:
        return jsonify({"error": "book_id not found"}), 404
    sample_vecs = []
    for vid in b.get("vector_ids", [])[:6]:
        vmeta = metadata["vectors"].get(vid, {})
        sample_vecs.append({"vector_id": vid, "text": vmeta.get("text", "")})
    out = {**b, "samples": sample_vecs}
    return jsonify(out)

@APP.route("/mcp/delete_book", methods=["POST"])
def delete_book():
    """
    Request JSON: { "book_id": "..." }
    Deletes all vectors and metadata for the book and rebuilds the FAISS index.
    """
    body = request.get_json(force=True) or {}
    book_id = body.get("book_id")
    if not book_id:
        return jsonify({"error": "book_id required"}), 400
    if book_id not in metadata.get("books", {}):
        return jsonify({"error": "book_id not found"}), 404

    remove_vids = set(metadata["books"][book_id].get("vector_ids", []))
    # remove vectors and index mapping
    for vid in remove_vids:
        metadata["vectors"].pop(vid, None)
    metadata["index_id_list"] = [vid for vid in metadata.get("index_id_list", []) if vid not in remove_vids]
    # remove book record
    metadata["books"].pop(book_id, None)
    safe_write_json(META_PATH, metadata)

    # rebuild index from remaining vectors
    try:
        remaining_vids = metadata.get("index_id_list", [])
        if not remaining_vids:
            # reset empty index
            if metadata.get("embed_dim", 0):
                init_faiss(metadata.get("embed_dim"))
            else:
                _ = None
            faiss.write_index(_index) if _index is not None else None
            return jsonify({"status": "deleted", "remaining_vectors": 0})

        emb_list = []
        for vid in remaining_vids:
            v = metadata["vectors"].get(vid, {})
            emb = v.get("embedding")
            if emb is None:
                return jsonify({"error": f"Missing stored embedding for vector {vid}, cannot rebuild index"}), 500
            emb_list.append(emb)

        emb_np = np.array(emb_list, dtype=np.float32)
        emb_np = normalize_vectors(emb_np)
        init_faiss(emb_np.shape[1])
        _index.add(emb_np)
        faiss.write_index(_index, index_path)
        return jsonify({"status": "deleted", "remaining_vectors": len(remaining_vids)})
    except Exception as e:
        print("[mcp] Rebuild error:", e)
        return jsonify({"error": f"Failed to rebuild index after deletion: {e}"}), 500

# Health
@APP.route("/mcp/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "indexed_vectors": len(metadata.get("index_id_list", [])), "embed_dim": metadata.get("embed_dim", 0)})

if __name__ == "__main__":
    print("[mcp] Starting MCP service on port 8001")
    APP.run(host="0.0.0.0", port=8001, debug=True)
