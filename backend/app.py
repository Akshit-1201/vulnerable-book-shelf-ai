# backend/app.py (logging cleaned: minimal, readable logs; no logic changes)
import os
import re
import json
import logging
import sqlite3
import requests
from typing import Optional, List, Dict, Any
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS

# -------------------- Config & Logging --------------------
# Keep logs concise and at INFO level for normal operation.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backend")

app = Flask(__name__)
CORS(app)  # dev: allow all origins

# Resolve DB path to absolute (default relative to project root)
DEFAULT_DB = os.path.join(os.path.dirname(__file__), "../data/database.db")
DB_PATH = os.getenv("DB_PATH", DEFAULT_DB)
DB_PATH = os.path.abspath(DB_PATH)

LLM_API = os.getenv("LLM_API", "http://127.0.0.1:5000/query")
MCP_API = os.getenv("MCP_API", "http://127.0.0.1:8001")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# Request timeouts configurable via env (seconds)
DEFAULT_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))

# -------------------- Utilities --------------------
def filter_resp_headers(headers: dict) -> dict:
    """
    Remove hop-by-hop headers which may cause issues when proxying responses.
    """
    hop_by_hop = {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailer", "transfer-encoding", "upgrade"
    }
    return {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}

# ----------------------- DB Helpers -----------------------
def get_db_connection():
    """
    Use check_same_thread=False to be tolerant in dev multi-threaded envs.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_db_schema() -> Dict[str, List[str]]:
    """
    Extract current schema from SQLite database.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cur.fetchall()
        schema = {}
        for row in tables:
            table = row[0]
            if table.startswith("sqlite_"):
                continue
            cur.execute(f"PRAGMA table_info({table});")
            cols = cur.fetchall()
            schema[table] = [col[1] for col in cols]  # col[1] = column name
        return schema
    finally:
        conn.close()

def schema_as_text(schema: dict) -> str:
    return "\n".join([f"- {table}({', '.join(cols)})" for table, cols in schema.items()])

def run_sql_select(sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
    """Execute a SELECT SQL and return rows as list[dict]."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()

def run_sql_modify(sql: str, params: Optional[tuple] = None) -> int:
    """Execute INSERT/UPDATE/DELETE SQL and return affected rows count."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()

# -------------------- Request logging (minimal) --------------------
@app.before_request
def log_request_minimal():
    # Log concise request line only; avoid headers or full bodies to keep logs clean.
    try:
        logger.info("Request: %s %s from %s", request.method, request.path, request.remote_addr)
    except Exception:
        logger.exception("Error while logging request")

# -------------------- Health & Root --------------------
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "service": "backend",
        "status": "running",
        "db_path": DB_PATH,
        "llm_api": LLM_API,
        "mcp_api": MCP_API
    })

@app.route("/health", methods=["GET"])
def health():
    # Quick DB connectivity check
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1;")
        conn.close()
        db_ok = True
    except Exception:
        logger.exception("DB health check failed")
        db_ok = False

    return jsonify({"healthy": db_ok}), (200 if db_ok else 500)

@app.route("/version", methods=["GET"])
def version():
    return jsonify({
        "name": "BookShelf-AI Backend",
        "version": "1.0.0",
        "db_path": DB_PATH,
        "llm_api": LLM_API,
        "mcp_api": MCP_API
    })

# ==================== AUTH ====================
@app.route("/signup", methods=["POST"])
def signup():
    data = request.json or {}
    required = ["username", "email", "password", "phone"]
    if not all(k in data and str(data[k]).strip() for k in required):
        return jsonify({"error": "Missing required fields"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Intentionally include role (default 'user') for version-2.
        cur.execute(
            "INSERT INTO users (username, email, password, phone_number, role) VALUES (?,?,?,?,?)",
            (data["username"], data["email"], data["password"], data["phone"], "user"),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        return jsonify({"error": f"Integrity error: {e}"}), 400
    except sqlite3.OperationalError:
        # Fallback in case DB doesn't have role column (backwards compatibility)
        try:
            cur.execute(
                "INSERT INTO users (username, email, password, phone_number) VALUES (?,?,?,?)",
                (data["username"], data["email"], data["password"], data["phone"]),
            )
            conn.commit()
        except Exception as e2:
            conn.close()
            return jsonify({"error": f"DB error: {e2}"}), 500
    finally:
        conn.close()

    logger.info("New user created: %s", data.get("email"))
    return jsonify({"message": "User Created"}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (email, password))
    user = cur.fetchone()
    conn.close()

    if user:
        role = user["role"] if "role" in user.keys() else "user"
        logger.info("User login: %s (role=%s)", email, role)
        return jsonify({
            "message": "Login Successful",
            "role": role,
            "user_id": user["id"],
            "username": user["username"]
        })
    logger.info("Failed login attempt: %s", email)
    return jsonify({"error": "Invalid Credentials"}), 401

# ----------------------- LLM Helpers (unchanged logic) -----------------------
GREET_RE = re.compile(r"\b(hi|hello|hey|hola|namaste|good (morning|afternoon|evening))\b", re.I)
THANKS_RE = re.compile(r"\b(thanks|thank you|tysm)\b", re.I)
BYE_RE = re.compile(r"\b(bye|goodbye|see ya|cya|see you)\b", re.I)

BOOK_HINT_WORDS = [
    "book", "author", "title", "genre", "rating", "published", "publisher", "isbn",
    "pages", "language", "summary", "recommend", "similar", "series"
]

def simple_intent(q: str) -> str:
    ql = (q or "").lower().strip()
    if not ql:
        return "unknown"
    if any(word in ql for word in ["delete", "remove", "drop"]):
        return "db_delete"
    DB_HINT_WORDS = [
        "user", "users", "users table", "users_table", "table", "tables", "row", "rows",
        "column", "columns", "insert", "update", "select", "find", "list", "show",
        "filter", "where", "count", "all the", "everything", "dump", "schema"
    ]
    if any(w in ql for w in DB_HINT_WORDS):
        return "db_query"
    if any(w in ql for w in BOOK_HINT_WORDS):
        return "db_query"
    if GREET_RE.search(ql) or THANKS_RE.search(ql) or BYE_RE.search(ql):
        return "chitchat"
    return "chitchat"

def llm_text(prompt: str) -> str:
    try:
        r = requests.post(LLM_API, json={"prompt": prompt, "mode": "text"}, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return (r.json().get("text") or "").strip()
    except Exception:
        logger.exception("LLM text call failed")
        return (
            "I'm BookShelf-AI. I can chat and answer book questions from our library. "
            "Try asking by title, author, genre, or other filters."
        )

def llm_sql(prompt: str) -> str:
    try:
        r = requests.post(LLM_API, json={"prompt": prompt, "mode": "sql"}, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return (r.json().get("sql") or "").strip()
    except Exception:
        logger.exception("LLM SQL call failed")
        return ""

def llm_fallback_answer(user_query: str) -> str:
    system_hint = (
        "You are BookShelf-AI. Be friendly and concise. You can chat generally, "
        "but you specialize in books from our library."
    )
    return llm_text(f"{system_hint}\n\nUser: {user_query}")

def generate_sql(query: str, schema_text: str, allow_modify: bool = False) -> Optional[str]:
    allowed_operations = "SELECT" if not allow_modify else "SELECT, INSERT, UPDATE, DELETE"
    prompt = f"""
You are a text-to-SQL assistant for a SQLite books database.

User request: {query}

Database schema:
{schema_text}

Rules:
- Output ONLY a single valid SQLite statement ({allowed_operations}).
- Do NOT include explanations, markdown, comments, or multiple statements.
- Use exact table and column names as in the schema.
- If the request cannot be answered with the schema, return exactly: NO_SQL
"""
    raw_sql = llm_sql(prompt)
    if not raw_sql or "NO_SQL" in raw_sql:
        return ""
    if not allow_modify:
        if raw_sql.strip().lower().startswith(("insert", "update", "delete", "drop", "create", "alter")):
            return ""
    sql_pattern = r"(?is)\b(select|insert|update|delete)\b.*"
    m = re.search(sql_pattern, raw_sql)
    return m.group(0).strip() if m else ""

def summarize_results(rows, user_query: str) -> str:
    preview = rows[:20]
    prompt = f"""
You are BookShelf-AI. Summarize the following SQLite query results for the user.

User query: {user_query}

Results JSON (preview, up to 20 rows):
{json.dumps(preview, ensure_ascii=False)}

Write a concise, friendly answer. Use bullet points if helpful. Do not invent fields.
"""
    return llm_text(prompt)

# ==================== SEARCH (Hybrid) ====================
@app.route("/search", methods=["POST"])
def search():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    user_id = data.get("user_id")

    if not query:
        return jsonify({"error": "Empty query"}), 400

    # Try MCP RAG first
    try:
        rag_resp = requests.post(f"{MCP_API}/mcp/search", json={
            "query": query,
            "user_id": user_id
        }, timeout=20)
        if rag_resp.ok:
            rag_data = rag_resp.json()
            if rag_data.get("answer") or rag_data.get("results"):
                return jsonify(rag_data)
    except Exception:
        logger.exception("MCP search call failed or timed out; falling back to DB")

    schema = get_db_schema()
    schema_text = schema_as_text(schema)
    intent = simple_intent(query)

    # 1) Chit-chat route
    if intent == "chitchat":
        answer = llm_fallback_answer(query)
        return jsonify({
            "results": [],
            "generated_sql": "",
            "answer": answer,
            "intent": "chitchat"
        })

    # 2) Delete route
    if intent == "db_delete":
        sql = generate_sql(query, schema_text, allow_modify=True)
        if not sql:
            answer = llm_fallback_answer(
                "I couldn't understand how to delete that. Try being more specific about what you want to delete from which table."
            )
            return jsonify({
                "results": [{"info": "Could not generate delete SQL"}],
                "generated_sql": "",
                "answer": answer,
                "intent": "db_delete_failed"
            })

        if not sql.strip().lower().startswith("delete"):
            return jsonify({
                "results": [{"error": "Not a valid delete operation"}],
                "generated_sql": sql,
                "answer": "I can only process DELETE statements for delete requests.",
                "intent": "db_delete_rejected"
            }), 400

        try:
            affected_rows = run_sql_modify(sql)
            answer = f"Successfully deleted {affected_rows} record(s) from the database."
            return jsonify({
                "results": [{"affected_rows": affected_rows}],
                "generated_sql": sql,
                "answer": answer,
                "intent": "db_delete_success"
            })
        except Exception as e:
            logger.exception("Error executing delete SQL")
            return jsonify({
                "results": [{"error": str(e)}],
                "generated_sql": sql,
                "answer": "There was an error executing the delete operation.",
                "intent": "db_delete_error"
            }), 500

    # 3) Regular DB query route
    sql = generate_sql(query, schema_text, allow_modify=False)
    if not sql:
        answer = llm_fallback_answer(
            f"The user asked: {query}\nWe could not generate SQL. Offer a helpful response and suggest how to ask for books by title/author/genre/filters."
        )
        return jsonify({
            "results": [{"info": "No valid SQL generated"}],
            "generated_sql": "",
            "answer": answer,
            "intent": "db_query_failed"
        })

    if not sql.strip().lower().startswith("select"):
        return jsonify({
            "results": [{"error": "Only SELECT statements are allowed for regular queries"}],
            "generated_sql": sql,
            "answer": "For safety, only read-only SELECT queries are executed for regular searches.",
            "intent": "db_query_rejected"
        }), 400

    try:
        rows = run_sql_select(sql)
    except Exception as e:
        logger.exception("Error running SQL")
        return jsonify({
            "results": [{"error": str(e)}],
            "generated_sql": sql,
            "answer": "There was an error running the query.",
            "intent": "db_error"
        }), 500

    answer = summarize_results(rows, query)
    return jsonify({
        "results": rows,
        "generated_sql": sql,
        "answer": answer,
        "intent": "db_query"
    })

# ==================== ADMIN (VULNERABLE: frontend-only gating) ====================
@app.route("/books", methods=["GET"])
def list_books():
    try:
        rows = run_sql_select("SELECT id, title, author, genre, COALESCE(status, '') AS status FROM books;")
        return jsonify({"books": rows})
    except Exception as e:
        logger.exception("Error listing books")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/add_book", methods=["POST"])
def admin_add_book():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    author = (data.get("author") or "").strip()
    genre = (data.get("genre") or "").strip()
    if not title or not author:
        return jsonify({"error": "title & author required"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO books (title, author, genre) VALUES (?,?,?)",
            (title, author, genre)
        )
        conn.commit()
        conn.close()
        logger.info("Added book: %s by %s", title, author)
        return jsonify({"message": "Book added"}), 201
    except Exception as e:
        logger.exception("Error adding book")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/edit_book/<int:book_id>", methods=["PUT"])
def admin_edit_book(book_id):
    data = request.get_json(silent=True) or {}
    fields = []
    vals = []
    for k in ("title", "author", "genre"):
        if k in data:
            fields.append(f"{k} = ?")
            vals.append(data[k])
    if not fields:
        return jsonify({"error": "No fields to update"}), 400
    vals.append(book_id)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f"UPDATE books SET {', '.join(fields)} WHERE id = ?", vals)
        conn.commit()
        affected = cur.rowcount
        conn.close()
        logger.info("Edited book id=%s affected=%s", book_id, affected)
        return jsonify({"message": "Book updated", "affected": affected})
    except Exception as e:
        logger.exception("Error editing book")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/delete_book/<int:book_id>", methods=["DELETE"])
def admin_delete_book(book_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM books WHERE id = ?", (book_id,))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        logger.info("Deleted book id=%s affected=%s", book_id, affected)
        return jsonify({"message": "Book deleted", "affected": affected})
    except Exception as e:
        logger.exception("Error deleting book")
        return jsonify({"error": str(e)}), 500

@app.route("/admin/users", methods=["GET"])
def admin_users():
    try:
        rows = run_sql_select("SELECT id, username, email, password, role FROM users;")
        return jsonify({"users": rows})
    except Exception as e:
        logger.exception("Error listing users")
        return jsonify({"error": str(e)}), 500

# ------------------- ADMIN: User management (VULNERABLE) -------------------
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
        logger.info("Added user: %s (role=%s)", username, role)
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
        logger.info("Edited user id=%s affected=%s", user_id, affected)
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
        logger.info("Deleted user id=%s affected=%s", user_id, affected)
        return jsonify({"message": "User deleted", "affected": affected})
    except Exception as e:
        logger.exception("Error deleting user")
        return jsonify({"error": str(e)}), 500

# ==================== MCP / INGEST endpoints ====================
@app.route("/ingest", methods=["POST"])
def ingest():
    """
    Receives multipart/form-data from frontend and proxies the upload to the MCP service.
    Expected form fields: pdf (file), user_id, title, author, book_id (optional)
    Returns whatever MCP returns.
    """
    user_id = request.form.get("user_id")
    title = request.form.get("title")
    author = request.form.get("author")
    book_id = request.form.get("book_id")
    pdf = request.files.get("pdf")

    if not user_id or not title or not author or not pdf:
        return jsonify({"error": "Missing Required Fields: user_id, title, author, pdf"}), 400

    try:
        # Ensure the file stream is at start
        try:
            pdf.stream.seek(0)
        except Exception:
            pass

        files = {"pdf": (pdf.filename, pdf.stream, pdf.mimetype)}
        data = {"user_id": user_id, "title": title, "author": author}
        if book_id:
            data["book_id"] = book_id

        resp = requests.post(f"{MCP_API}/mcp/upload", files=files, data=data, timeout=300)
        headers = filter_resp_headers(resp.headers)
        logger.info("Forwarded ingest upload for user_id=%s title=%s (status=%s)", user_id, title, resp.status_code)
        return (resp.content, resp.status_code, headers)
    except Exception:
        logger.exception("Failed to forward to MCP")
        return jsonify({"error": "Failed to forward to MCP"}), 500

@app.route("/ingest/status/<upload_id>", methods=["GET"])
def ingest_status(upload_id):
    """
    Proxy to MCP Server so that Frontend can poll
    """
    try:
        resp = requests.get(f"{MCP_API}/mcp/status/{upload_id}", timeout=DEFAULT_TIMEOUT)
        headers = filter_resp_headers(resp.headers)
        return (resp.content, resp.status_code, headers)
    except Exception:
        logger.exception("Failed to contact MCP status")
        return jsonify({"error": "Failed to contact MCP status"}), 500

# -------------------- Run --------------------
if __name__ == "__main__":
    logger.info("Starting backend on 0.0.0.0:%s", BACKEND_PORT)
    # Disabled debug flag to avoid verbose Flask debug logs in normal runs
    app.run(host="0.0.0.0", port=BACKEND_PORT, debug=False)
