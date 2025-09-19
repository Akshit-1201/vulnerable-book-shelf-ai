# backend/app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import requests
import os
import re
import json

app = Flask(__name__)
CORS(app)

DB_PATH = os.getenv("DB_PATH", "../data/database.db")
# Your local LLM service. Expected to accept {"prompt": "...", "mode": "sql"|"text"}.
LLM_API = os.getenv("LLM_API", "http://127.0.0.1:5000/query")

# ----------------------- DB Helpers -----------------------

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_db_schema() -> dict:
    """Extract current schema from SQLite database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cur.fetchall()
    
    schema = {}
    for row in tables:
        table = row[0]
        # skip sqlite internal tables if any
        if table.startswith("sqlite_"):
            continue
        cur.execute(f"PRAGMA table_info({table});")
        cols = cur.fetchall()
        schema[table] = [col[1] for col in cols]  # col[1] = column name
    
    conn.close()
    return schema

def schema_as_text(schema: dict) -> str:
    return "\n".join([f"- {table}({', '.join(cols)})" for table, cols in schema.items()])

def run_sql_select(sql: str):
    """Execute a SELECT SQL and return rows as list[dict]."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()

def run_sql_modify(sql: str):
    """Execute INSERT/UPDATE/DELETE SQL and return affected rows count."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()

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
        return jsonify({"error": f"Integrity error: {e}"}), 400
    except sqlite3.OperationalError as e:
        # Fallback in case DB doesn't have role column (backwards compatibility)
        try:
            cur.execute(
                "INSERT INTO users (username, email, password, phone_number) VALUES (?,?,?,?)",
                (data["username"], data["email"], data["password"], data["phone"]),
            )
            conn.commit()
        except Exception as e2:
            return jsonify({"error": f"DB error: {e2}"}), 500
    finally:
        conn.close()

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
        # return role (if present)
        role = user["role"] if "role" in user.keys() else "user"
        return jsonify({"message": "Login Successful", "role": role})

    return jsonify({"error": "Invalid Credentials"}), 401

# ----------------------- LLM Helpers -----------------------

GREET_RE = re.compile(r"\b(hi|hello|hey|hola|namaste|good (morning|afternoon|evening))\b", re.I)
THANKS_RE = re.compile(r"\b(thanks|thank you|tysm)\b", re.I)
BYE_RE = re.compile(r"\b(bye|goodbye|see ya|cya|see you)\b", re.I)

BOOK_HINT_WORDS = [
    "book", "author", "title", "genre", "rating", "published", "publisher", "isbn",
    "pages", "language", "summary", "recommend", "similar", "series"
]

def simple_intent(q: str) -> str:
    """
    Lightweight router. Prioritize DB-related keywords first so queries like
    "Hey, list all the users in your database" are treated as DB queries, not chitchat.
    """
    ql = (q or "").lower().strip()
    if not ql:
        return "unknown"

    # Check for delete operations first
    if any(word in ql for word in ["delete", "remove", "drop"]):
        return "db_delete"

    # Strong DB-related hints (checked first)
    DB_HINT_WORDS = [
        "user", "users", "users table", "users_table", "table", "tables", "row", "rows",
        "column", "columns", "insert", "update", "select", "find", "list", "show",
        "filter", "where", "count", "all the", "everything", "dump", "schema"
    ]
    
    if any(w in ql for w in DB_HINT_WORDS):
        return "db_query"

    # Book-specific hints (kept for book-focused queries)
    if any(w in ql for w in BOOK_HINT_WORDS):
        return "db_query"

    # Greeting/thanks/bye - fallback to chitchat
    if GREET_RE.search(ql) or THANKS_RE.search(ql) or BYE_RE.search(ql):
        return "chitchat"

    # Default to chitchat for anything else
    return "chitchat"

def llm_text(prompt: str) -> str:
    """
    Call your LLM for natural-language output.
    """
    try:
        r = requests.post(LLM_API, json={"prompt": prompt, "mode": "text"}, timeout=30)
        r.raise_for_status()
        return (r.json().get("text") or "").strip()
    except Exception as e:
        # Final fallback (short canned)
        return (
            "I'm BookShelf-AI. I can chat and answer book questions from our library. "
            "Try asking by title, author, genre, or other filters."
        )

def llm_sql(prompt: str) -> str:
    """
    Call your LLM for SQL-only output (no prose).
    """
    try:
        r = requests.post(LLM_API, json={"prompt": prompt, "mode": "sql"}, timeout=30)
        r.raise_for_status()
        return (r.json().get("sql") or "").strip()
    except Exception:
        return ""

def llm_fallback_answer(user_query: str) -> str:
    """
    Friendly conversational answer (for greetings/general chat or fallback).
    """
    system_hint = (
        "You are BookShelf-AI. Be friendly and concise. You can chat generally, "
        "but you specialize in books from our library."
    )
    return llm_text(f"{system_hint}\n\nUser: {user_query}")

def generate_sql(query: str, schema_text: str, allow_modify: bool = False) -> str | None:
    """
    Ask LLM to generate a single valid SQLite statement for the provided schema.
    Returns empty string if not possible.
    """
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
    
    # If we don't allow modify operations, reject them
    if not allow_modify:
        if raw_sql.strip().lower().startswith(("insert", "update", "delete", "drop", "create", "alter")):
            return ""
    
    # Extract the SQL statement (be tolerant if model added stray text)
    sql_pattern = r"(?is)\b(select|insert|update|delete)\b.*"
    m = re.search(sql_pattern, raw_sql)
    return m.group(0).strip() if m else ""

def summarize_results(rows, user_query: str) -> str:
    """
    Ask LLM to turn raw rows into a helpful human answer.
    """
    preview = rows[:20]  # keep token usage sane
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
    
    if not query:
        return jsonify({"error": "Empty query"}), 400

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
                f"I couldn't understand how to delete that. "
                f"Try being more specific about what you want to delete from which table."
            )
            return jsonify({
                "results": [{"info": "Could not generate delete SQL"}],
                "generated_sql": "",
                "answer": answer,
                "intent": "db_delete_failed"
            })
        
        # Make sure it's actually a DELETE statement
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
            return jsonify({
                "results": [{"error": str(e)}],
                "generated_sql": sql,
                "answer": "There was an error executing the delete operation.",
                "intent": "db_delete_error"
            }), 500

    # 3) Regular DB query route
    sql = generate_sql(query, schema_text, allow_modify=False)
    if not sql:
        # Couldn't produce SQL — give a helpful conversational answer
        answer = llm_fallback_answer(
            f"The user asked: {query}\nWe could not generate SQL. "
            "Offer a helpful response and suggest how to ask for books by title/author/genre/filters."
        )
        return jsonify({
            "results": [{"info": "No valid SQL generated"}],
            "generated_sql": "",
            "answer": answer,
            "intent": "db_query_failed"
        })

    # Enforce read-only for regular queries (defense-in-depth)
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
    """Public listing of books (used by admin panel + UI)."""
    try:
        rows = run_sql_select("SELECT id, title, author, genre FROM books;")
        return jsonify({"books": rows})
    except Exception as e:
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
        return jsonify({"message": "Book added"}), 201
    except Exception as e:
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
        return jsonify({"message": "Book updated", "affected": affected})
    except Exception as e:
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
        return jsonify({"message": "Book deleted", "affected": affected})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/users", methods=["GET"])
def admin_users():
    """
    Intentionally returns all users (including plaintext passwords) for demo purposes.
    WARNING: vulnerable endpoint — no auth or role enforcement.
    """
    try:
        rows = run_sql_select("SELECT id, username, email, password, role FROM users;")
        return jsonify({"users": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------------- ADMIN: User management (VULNERABLE) -------------------

@app.route("/admin/add_user", methods=["POST"])
def admin_add_user():
    """
    Add a new user. Intentionally stores password in plaintext for the demo.
    Expected JSON body: { "username": "...", "email": "...", "password": "...", "phone": "...", "role": "user"|"admin" }
    """
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
        return jsonify({"error": f"Integrity error: {e}"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/edit_user/<int:user_id>", methods=["PUT"])
def admin_edit_user(user_id):
    """
    Edit user fields (username, email, password, phone_number, role).
    Body contains the fields to update.
    """
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
        return jsonify({"error": str(e)}), 500

@app.route("/admin/delete_user/<int:user_id>", methods=["DELETE"])
def admin_delete_user(user_id):
    """
    Delete a user by id.
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        affected = cur.rowcount
        conn.close()
        return jsonify({"message": "User deleted", "affected": affected})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
