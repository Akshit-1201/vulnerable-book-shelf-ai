import os
import sqlite3
import time
import json
import logging
from typing import Any, Dict, List, Optional
from flask import Flask, request, jsonify, g
from flask_cors import CORS
import requests

# ---------- Configuration ----------
DB_PATH = os.getenv("DB_PATH", "../data/database.db")
MCP_API = os.getenv("MCP_API", "http://127.0.0.1:8001")   # MCP service base URL
LLM_API = os.getenv("LLM_API", "http://127.0.0.1:5000")   # LLM service base URL
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

# ---------- Logging (clean) ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger("backend")

# ---------- Flask app ----------
app = Flask(__name__)
CORS(app)  # Keep CORS enabled; frontend uses localhost:3000

# ---------- DB helpers ----------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def run_sql_select(query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
    """
    Run a SELECT statement and return list-of-dict rows.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

def run_sql_modify(query: str, params: Optional[tuple] = None) -> int:
    """
    Run INSERT/UPDATE/DELETE. Returns lastrowid or number of affected rows.
    Note: This helper uses parameterized queries when params provided.
    """
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        conn.commit()
        return cur.lastrowid if cur.lastrowid else cur.rowcount
    finally:
        conn.close()

# Initialize minimal schema if missing (safe idempotent)
def init_db():
    logger.info("Ensuring database schema exists at %s", DB_PATH)
    conn = get_db_connection()
    cur = conn.cursor()
    # Very minimal tables: users, books
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        email TEXT UNIQUE,
        password TEXT,
        phone TEXT,
        role TEXT DEFAULT 'user',
        created_at REAL
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS books (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        author TEXT,
        genre TEXT,
        status TEXT,
        created_at REAL
        -- You may optionally store mcp_book_id/upload_id here if you want to link
    )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- Utility helpers ----------
def json_ok(data):
    return jsonify(data), 200

def json_err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code

def safe_extract_text_candidate(nl_text: str) -> str:
    """
    Heuristic to extract a likely book title from a natural-language deletion sentence.
    Example inputs:
      - "delete the Biomaterials book from your database"
      - "please remove Biomaterials"
      - "erase the book titled 'Biomaterials'"

    Returns a cleaned candidate string for matching.
    """
    s = nl_text or ""
    s = s.strip()
    # remove polite words and common phrases
    for pat in ["please", "kindly", "could you", "would you", "delete", "remove", "erase", "the", "book", "books", "from", "database", "your", "my", "library"]:
        s = s.replace(pat, "")
        s = s.replace(pat.title(), "")
    # remove punctuation
    s = s.replace("'", "").replace('"', "").replace(".", "").replace("?", "").strip()
    return s

def find_mcp_book_by_title_or_uploadid(candidate: str) -> Optional[Dict[str, Any]]:
    """
    Query MCP /mcp/list_books and try to find a matching entry by title, upload_id, or filename.
    Matching strategy: exact lower-case match first, then substring match.
    Returns the MCP book object (with book_id) or None.
    """
    try:
        resp = requests.get(f"{MCP_API}/mcp/list_books", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        mbooks = data.get("books", []) if isinstance(data, dict) else data
        cand = (candidate or "").strip().lower()
        if not cand:
            return None
        # exact match
        for b in mbooks:
            title = (b.get("title") or "").strip().lower()
            uid = (b.get("book_id") or "").strip().lower()
            if title == cand or uid == cand:
                return b
        # substring match (title contains cand or cand contains title)
        for b in mbooks:
            title = (b.get("title") or "").strip().lower()
            uid = (b.get("book_id") or "").strip().lower()
            if cand in title or title in cand or cand in uid:
                return b
        return None
    except Exception as e:
        logger.warning("Could not query MCP list_books: %s", e)
        return None

# ---------- Routes ----------

@app.route("/health", methods=["GET"])
def health():
    return json_ok({"status": "ok", "service": "backend", "mcp_api": MCP_API, "llm_api": LLM_API})

# --- Auth endpoints (simple, demo-only) ---
@app.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True, silent=True) or {}
    username = data.get("username")
    email = data.get("email")
    password = data.get("password")
    phone = data.get("phone", "")
    if not username or not email or not password:
        return json_err("username, email, password required", 400)
    try:
        now = time.time()
        # parameterized insert
        run_sql_modify("INSERT INTO users (username, email, password, phone_number, created_at) VALUES (?, ?, ?, ?, ?)",
                       (username, email, password, phone, now))
        logger.info("New user signed up: %s", email)
        # return newly created user id (best-effort)
        rows = run_sql_select("SELECT id FROM users WHERE email = ?", (email,))
        uid = rows[0]["id"] if rows else None
        return json_ok({"message": "signup successful", "user_id": uid})
    except Exception as e:
        logger.exception("Signup failed")
        return json_err(f"Signup failed: {e}", 500)

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get("email")
    password = data.get("password")
    if not email or not password:
        return json_err("email and password required", 400)
    try:
        rows = run_sql_select("SELECT id, username, role FROM users WHERE email = ? AND password = ?", (email, password))
        if not rows:
            return json_err("invalid credentials", 401)
        user = rows[0]
        logger.info("User login: %s", email)
        return json_ok({"message": "login successful", "user_id": user["id"], "username": user["username"], "role": user.get("role", "user")})
    except Exception as e:
        logger.exception("Login error")
        return json_err("login failed", 500)

# --- Admin endpoints ---
@app.route("/admin/users", methods=["GET"])
def admin_users():
    try:
        rows = run_sql_select("SELECT id, username, email, password, role FROM users;")
        return jsonify({"users": rows})
    except Exception as e:
        logger.exception("Error listing users")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/add_user", methods=["POST"])
def admin_add_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()
    phone = (data.get("phone") or "").strip()
    role = (data.get("role") or "user").strip()

    if not username or not email or not password:
        return jsonify({"error": "username, email and password are required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, email, password, phone_number, role) VALUES (?,?,?,?,?)",
            (username, email, password, phone, role)
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "User added"}), 201
    except sqlite3.IntegrityError as e:
        logger.exception("Integrity error adding user")
        return jsonify({"error": f"Integrity error: {e}"}), 400
    except Exception as e:
        logger.exception("Error adding user")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/edit_user/<int:user_id>", methods=["PUT"])
def admin_edit_user(user_id):
    data = request.get_json(silent=True) or {}
    fields = []
    vals = []
    mapping = {
        "username": "username",
        "email": "email",
        "password": "password",
        "phone": "phone_number",
        "role": "role"
    }
    for k, col in mapping.items():
        if k in data:
            fields.append(f"{col} = ?")
            vals.append(data[k])
    if not fields:
        return jsonify({"error": "No fields to update"}), 400
    vals.append(user_id)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", vals)
        conn.commit()
        affected = cur.rowcount
        conn.close()
        return jsonify({"message": "User updated", "affected": affected})
    except Exception as e:
        logger.exception("Error editing user")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/delete_user/<int:user_id>", methods=["DELETE"])
def admin_delete_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        return jsonify({"message": "User deleted", "affected": affected})
    except Exception as e:
        logger.exception("Error deleting user")
        return jsonify({"error": str(e)}), 500

# --- Books endpoints (backend DB) ---
@app.route("/books", methods=["GET"])
def list_books():
    try:
        rows = run_sql_select("SELECT id, title, author, genre, status, created_at FROM books ORDER BY created_at DESC")
        # Note: we do not include MCP book_id here by default (unless you store it)
        return json_ok({"books": rows})
    except Exception as e:
        logger.exception("Failed to list books")
        return json_err("failed to list books", 500)

@app.route("/admin/add_book", methods=["POST"])
def admin_add_book():
    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title")
    author = data.get("author", "")
    genre = data.get("genre", "")
    if not title:
        return json_err("title required", 400)
    try:
        now = time.time()
        rid = run_sql_modify("INSERT INTO books (title, author, genre, status, created_at) VALUES (?, ?, ?, ?, ?)",
                             (title, author, genre, "created", now))
        logger.info("Book added to backend DB: %s (id=%s)", title, rid)
        return json_ok({"message": "book added", "id": rid})
    except Exception as e:
        logger.exception("Failed to add book")
        return json_err("failed to add book", 500)

@app.route("/admin/delete_book/<int:book_id>", methods=["DELETE"])
def admin_delete_book(book_id: int):
    """
    Deletes the book row from backend DB only.
    This does not touch the MCP index unless you call MCP separately.
    """
    try:
        # remove row
        affected = run_sql_modify("DELETE FROM books WHERE id = ?", (book_id,))
        if affected == 0:
            return json_err("book id not found", 404)
        logger.info("Deleted backend book id=%s", book_id)
        return json_ok({"status": "deleted", "backend_deleted_rows": affected})
    except Exception as e:
        logger.exception("Failed to delete backend book")
        return json_err("failed to delete book", 500)

# --- Proxy to MCP endpoints (optional convenience) ---
@app.route("/mcp/search", methods=["POST", "OPTIONS"])
def proxy_mcp_search():
    # Flask-CORS will handle OPTIONS headers; respond normally for POST
    if request.method == "OPTIONS":
        return ("", 200)
    try:
        body = request.get_json(force=True, silent=True) or {}
        resp = requests.post(f"{MCP_API}/mcp/search", json=body, timeout=REQUEST_TIMEOUT)
        return (resp.content, resp.status_code, resp.headers.items())
    except Exception as e:
        logger.exception("Proxy to MCP /mcp/search failed")
        return json_err("proxy to MCP failed", 500)

@app.route("/ingest", methods=["POST"])
def ingest_proxy():
    """
    Proxy file upload to MCP /mcp/upload so frontend can post to backend /ingest.
    """
    try:
        if "pdf" not in request.files:
            return json_err("pdf file required", 400)
        files = {"pdf": (request.files["pdf"].filename, request.files["pdf"].stream, request.files["pdf"].mimetype)}
        # forward other form fields
        data = {k: v for k, v in request.form.items()}
        resp = requests.post(f"{MCP_API}/mcp/upload", files=files, data=data, timeout=120)
        return (resp.content, resp.status_code, resp.headers.items())
    except Exception as e:
        logger.exception("Ingest proxy failed")
        return json_err("ingest failed", 500)

@app.route("/ingest/status/<upload_id>", methods=["GET"])
def ingest_status_proxy(upload_id):
    try:
        resp = requests.get(f"{MCP_API}/mcp/status/{upload_id}", timeout=REQUEST_TIMEOUT)
        return (resp.content, resp.status_code, resp.headers.items())
    except Exception as e:
        logger.warning("Could not query MCP status for upload_id=%s: %s", upload_id, e)
        return json_err("mcp status unavailable", 500)

# --- Natural-language delete endpoint (server-side) ---
@app.route("/admin/nl_delete", methods=["POST"])
def admin_nl_delete():
    """
    Accepts JSON: { "nl": "delete the Biomaterials book from your database" }
    Attempts to:
      1) extract a title candidate
      2) find MCP book via /mcp/list_books
      3) call MCP /mcp/delete_book {book_id}
      4) remove backend book row if present
    """
    body = request.get_json(force=True, silent=True) or {}
    nl = body.get("nl", "")
    if not nl or not isinstance(nl, str):
        return json_err("nl (natural language) required", 400)

    # Heuristic extraction
    candidate = safe_extract_text_candidate(nl)
    if not candidate:
        return json_err("could not extract book title from natural language", 400)

    logger.info("NL delete request; candidate='%s'", candidate)
    # Find MCP book
    mbook = find_mcp_book_by_title_or_uploadid(candidate)
    if not mbook:
        logger.info("No MCP book matched candidate='%s'", candidate)
        return json_err("no matching book found in MCP registry", 404)

    book_id = mbook.get("book_id")
    if not book_id:
        logger.warning("MCP book missing book_id for entry: %s", mbook)
        return json_err("matched MCP entry missing book_id", 500)

    # Call MCP delete endpoint
    try:
        dresp = requests.post(f"{MCP_API}/mcp/delete_book", json={"book_id": book_id}, timeout=REQUEST_TIMEOUT)
        if dresp.status_code >= 400:
            logger.warning("MCP delete returned status %s: %s", dresp.status_code, dresp.text[:200])
            return (dresp.content, dresp.status_code, dresp.headers.items())
    except Exception as e:
        logger.exception("MCP delete call failed for book_id=%s", book_id)
        return json_err("mcp delete failed", 500)

    logger.info("MCP deleted book_id=%s successfully; now removing backend record if exists", book_id)

    # Try to remove backend book row if it matches title/author
    try:
        # Attempt to delete by title match (vulnerable behavior preserved only for LLM SQL -- here we use parameterized query)
        affected = run_sql_modify("DELETE FROM books WHERE lower(title) = ?", (candidate.lower(),))
        # If none deleted, try substring match
        if affected == 0:
            affected = run_sql_modify("DELETE FROM books WHERE lower(title) LIKE ?", (f"%{candidate.lower()}%",))
        logger.info("Backend delete affected rows=%s", affected)
    except Exception:
        logger.exception("Backend book row removal failed (non-fatal)")

    return json_ok({"status": "deleted", "mcp_book_id": book_id})

# --- LLM SQL execution endpoint (intentionally vulnerable demo) ---
@app.route("/llm/sql_execute", methods=["POST"])
def llm_sql_execute():
    """
    Demo endpoint that accepts raw SQL from the LLM and executes it.
    JSON: { "sql": "<sql_string>" }
    WARNING: This intentionally executes raw SQL without sanitization for the vulnerable demo.
    """
    body = request.get_json(force=True, silent=True) or {}
    raw_sql = body.get("sql", "")
    if not raw_sql:
        return json_err("sql required", 400)
    try:
        # Intentionally executing raw SQL (vulnerable by design for the project)
        rows = run_sql_select(raw_sql)  # may raise if not SELECT
        return json_ok({"rows": rows})
    except Exception as e:
        logger.exception("LLM SQL execution failed")
        return json_err(f"llm sql execution failed: {e}", 500)

# ---------- App entry ----------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    logger.info("Starting backend on port %s", port)
    # Run without debug to keep logs clean; Flask reloader may print extra messages but we avoid debug logs
    app.run(host="0.0.0.0", port=port, debug=False)
