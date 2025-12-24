# llm/app.py
"""
LLM microservice for text generation and embeddings using Google Generative AI SDK.

Endpoints:
  - GET  /            -> health check
  - POST /query       -> { "prompt": "...", "mode": "sql"|"text" } -> {"text": "..."} or {"sql": "..."}
  - POST /embed       -> { "text": "single" } or { "texts": ["one","two"] } -> {"embeddings": [[...], [...]]}

Notes:
  - Configure GEMINI_API_KEY in environment (required)
  - Optional env vars:
      GEMINI_TEXT_MODEL (default: "gemini-2.5-flash")
      GEMINI_EMBED_MODEL (default: "gemini-embedding-001")
      EMBED_BATCH_SIZE (default: 64)
"""
import os
import logging
from typing import List
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS

# third-party Google Generative AI SDK
import google.generativeai as genai

# load .env
load_dotenv()

# logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("llm_service")

# app
app = Flask(__name__)
CORS(app)

# Env / config
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY not found in environment (.env?)")
    raise ValueError("❌ GEMINI_API_KEY not found in environment (.env?)")

genai.configure(api_key=GEMINI_API_KEY)

TEXT_MODEL = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
EMBEDDING_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))


def _normalize_text_response(resp) -> str:
    """
    Normalize text response from various SDK return shapes into a single string.
    Works with:
      - objects with `.text`
      - objects with `.candidates` [...]
      - dict-like with 'text' or 'candidates'
      - fallback to str(resp)
    """
    try:
        # direct attribute style
        if hasattr(resp, "text") and isinstance(resp.text, str):
            return resp.text.strip()
    except Exception:
        pass

    try:
        if hasattr(resp, "candidates"):
            cands = resp.candidates
            if isinstance(cands, (list, tuple)) and cands:
                first = cands[0]
                for attr in ("content", "text", "display"):
                    if hasattr(first, attr):
                        val = getattr(first, attr)
                        if isinstance(val, str):
                            return val.strip()
    except Exception:
        pass

    try:
        if isinstance(resp, dict):
            if "text" in resp and isinstance(resp["text"], str):
                return resp["text"].strip()
            if "candidates" in resp and isinstance(resp["candidates"], list) and resp["candidates"]:
                first = resp["candidates"][0]
                for key in ("content", "text", "display"):
                    if key in first and isinstance(first[key], str):
                        return first[key].strip()
    except Exception:
        pass

    try:
        return str(resp).strip()
    except Exception:
        return ""


@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "message": "LLM Service (Gemini) — healthy",
        "text_model": TEXT_MODEL,
        "embed_model": EMBEDDING_MODEL
    })


@app.route("/query", methods=["POST"])
def query():
    """
    POST JSON:
      { "prompt": "...", "mode": "sql" | "text" }

    Returns:
      mode == "sql" -> { "sql": "<string>" }
      else            -> { "text": "<string>" }
    """
    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    mode = data.get("mode", "sql")

    if not isinstance(prompt, str) or not prompt.strip():
        return jsonify({"error": "Missing or invalid 'prompt' in JSON body"}), 400

    try:
        # Primary attempt: model's generate_content (keeps compatibility with older SDKs)
        try:
            model = genai.GenerativeModel(TEXT_MODEL)
            resp = model.generate_content(prompt)
        except Exception as e_primary:
            logger.debug("generate_content failed: %s", e_primary)
            # Fallback: genai.create(...) signature used by some SDKs
            try:
                resp = genai.create(model=TEXT_MODEL, input=prompt)
            except Exception as e_fallback:
                logger.exception("Both primary and fallback text generation calls failed")
                raise

        text = _normalize_text_response(resp)
        if mode == "sql":
            return jsonify({"sql": text})
        return jsonify({"text": text})
    except Exception as e:
        logger.exception("Error processing /query")
        return jsonify({"error": "LLM query failed", "detail": str(e)}), 500


def _extract_embeddings(raw) -> List[List[float]]:
    """
    Attempt to parse various embedding response shapes into List[List[float]].
    Handles:
      - dict with 'data' -> list of items containing 'embedding' / 'embeddings' / 'vector' / 'values'
      - top-level 'embeddings' or 'embedding'
      - a raw list-of-lists
    """
    embeddings = []
    try:
        if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], list):
            for item in raw["data"]:
                if isinstance(item, dict):
                    for key in ("embedding", "embeddings", "vector", "values"):
                        if key in item and isinstance(item[key], list):
                            # if nested list-of-lists, flatten appropriately
                            candidate = item[key]
                            if candidate and isinstance(candidate[0], (list, tuple)):
                                embeddings.extend([list(c) for c in candidate])
                            else:
                                embeddings.append(list(candidate))
                            break
                    else:
                        # try to find a numeric-list value
                        for v in item.values():
                            if isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v):
                                embeddings.append(list(v))
                                break
                else:
                    # item might itself be a list of numbers
                    if isinstance(item, (list, tuple)) and item and all(isinstance(x, (int, float)) for x in item):
                        embeddings.append(list(item))
        elif isinstance(raw, dict):
            for key in ("embeddings", "embedding", "vector", "values"):
                if key in raw and isinstance(raw[key], list):
                    candidate = raw[key]
                    if candidate and isinstance(candidate[0], (list, tuple)):
                        embeddings.extend([list(c) for c in candidate])
                    else:
                        embeddings.append(list(candidate))
                    break
        elif isinstance(raw, list):
            if raw and isinstance(raw[0], (list, tuple)):
                embeddings = [list(r) for r in raw]
            elif raw and all(isinstance(x, (int, float)) for x in raw):
                embeddings = [list(raw)]
    except Exception:
        logger.exception("Error while extracting embeddings")

    return embeddings


@app.route("/embed", methods=["POST"])
def embed():
    """
    POST JSON:
      { "text": "single string" }
    or
      { "texts": ["one", "two", ...] }

    Returns:
      { "embeddings": [[...], [...], ...] }
    """
    data = request.get_json(force=True, silent=True) or {}

    if "texts" in data and isinstance(data["texts"], list):
        texts = data["texts"]
    elif "text" in data and isinstance(data["text"], str):
        texts = [data["text"]]
    else:
        return jsonify({"error": "Provide 'text' (string) or 'texts' (list of strings) in the JSON body"}), 400

    if not all(isinstance(t, str) for t in texts):
        return jsonify({"error": "'texts' must be a list of strings"}), 400

    if len(texts) == 0:
        return jsonify({"error": "'texts' must contain at least one string"}), 400

    try:
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            # Primary call
            try:
                raw_result = genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=batch,
                    task_type="retrieval_document"
                )
            except Exception as e_embed:
                logger.debug("genai.embed_content failed: %s", e_embed)
                # fallback attempt
                try:
                    # raw_result = genai.embeddings.create(model=EMBEDDING_MODEL, input=batch)
                    raw_result = genai.embed_content(
                        model=EMBEDDING_MODEL,
                        content=batch,
                        task_type="retrieval_document"  # or "retrieval_query" depending on use case
                        )
                    
                except Exception as e_fb2:
                    logger.exception("Embedding calls failed for batch")
                    return jsonify({"error": "Embedding call failed for batch", "detail": str(e_fb2)}), 500

            batch_embeddings = _extract_embeddings(raw_result)
            if not batch_embeddings:
                logger.error("Could not parse embeddings for batch; raw preview: %s", str(raw_result)[:400])
                return jsonify({
                    "error": "Could not parse embeddings from model response",
                    "raw_preview": str(raw_result)[:400]
                }), 500

            all_embeddings.extend(batch_embeddings)

        # validate count
        if len(all_embeddings) != len(texts):
            logger.warning("Embedding count mismatch: inputs=%d embeddings=%d", len(texts), len(all_embeddings))
            return jsonify({
                "error": "Embedding count mismatch (inputs vs parsed embeddings)",
                "inputs": len(texts),
                "embeddings_parsed": len(all_embeddings)
            }), 500

        return jsonify({"embeddings": all_embeddings})
    except Exception as e:
        logger.exception("Embedding endpoint failed")
        return jsonify({"error": "Embedding Model Error", "detail": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
