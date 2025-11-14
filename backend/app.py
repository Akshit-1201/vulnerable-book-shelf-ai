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
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backend")

app = Flask(__name__)
CORS(app)

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "../data/database.db")
DB_PATH = os.getenv("DB_PATH", DEFAULT_DB)
DB_PATH = os.path.abspath(DB_PATH)

LLM_API = os.getenv("LLM_API", "http://127.0.0.1:5000/query")
MCP_API = os.getenv("MCP_API", "http://127.0.0.1:8001")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

DEFAULT_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))

# -------------------- Utilities --------------------
def filter_resp_headers(headers: dict) -> dict:
    hop_by_hop = {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailer", "transfer-encoding", "upgrade"
    }
    return {k: v for k, v in headers.items() if k.lower() not in hop_by_hop}

# ----------------------- DB Helpers -----------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_db_schema() -> Dict[str, List[str]]:
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
            schema[table] = [col[1] for col in cols]
        return schema
    finally:
        conn.close()

def schema_as_text(schema: dict) -> str:
    return "\n".join([f"- {table}({', '.join(cols)})" for table, cols in schema.items()])

def run_sql_select(sql: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
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

# -------------------- Request logging --------------------
@app.before_request
def log_request_minimal():
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
        cur.execute(
            "INSERT INTO users (username, email, password, phone_number, role) VALUES (?,?,?,?,?)",
            (data["username"], data["email"], data["password"], data["phone"], "user"),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        return jsonify({"error": f"Integrity error: {e}"}), 400
    except sqlite3.OperationalError:
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

# ----------------------- IMPROVED INTENT DETECTION -----------------------
GREET_RE = re.compile(r"\b(hi|hello|hey|hola|namaste|good (morning|afternoon|evening))\b", re.I)
THANKS_RE = re.compile(r"\b(thanks|thank you|tysm)\b", re.I)
BYE_RE = re.compile(r"\b(bye|goodbye|see ya|cya|see you)\b", re.I)

def detect_intent(query: str) -> dict:
    """
    Enhanced intent detection that distinguishes between:
    - user queries (SQLite)
    - book queries (MCP/Vector DB)
    - list all books (complete registry)
    - delete operations
    - chitchat
    
    Returns: {
        "intent": "user_query" | "book_query" | "list_all_books" | "delete_user" | "delete_book" | "chitchat",
        "target": <extracted target if applicable>
    }
    """
    ql = (query or "").lower().strip()
    if not ql:
        return {"intent": "unknown"}
    
    # Chitchat detection
    if GREET_RE.search(ql) or THANKS_RE.search(ql) or BYE_RE.search(ql):
        return {"intent": "chitchat"}
    
    # Delete detection
    is_delete = any(word in ql for word in ["delete", "remove", "drop", "erase"])
    
    # List ALL detection - check for "all" + "book" combinations
    has_all = any(word in ql for word in ["all", "every", "entire", "complete", "whole"])
    has_list_verb = any(word in ql for word in ["list", "show", "display", "give", "get", "fetch", "find"])
    has_book = any(word in ql for word in ["book", "books"])
    
    # If query asks for "all books" or "list all books" or similar
    if has_all and has_book and has_list_verb:
        return {"intent": "list_all_books"}
    
    # Alternative patterns: "what books are", "books present", "books in database"
    if has_book and any(phrase in ql for phrase in ["present in", "in database", "in the database", "are in", "are there"]):
        return {"intent": "list_all_books"}
    
    # USER-related keywords (strong indicators)
    USER_KEYWORDS = [
        "user", "users", "account", "accounts", "member", "members",
        "login", "signup", "email", "password", "phone", "role",
        "admin", "admins", "username", "usernames"
    ]
    
    # BOOK-related keywords
    BOOK_KEYWORDS = [
        "book", "books", "author", "title", "genre", "rating", 
        "published", "publisher", "isbn", "pages", "language", 
        "summary", "chapter", "novel", "story"
    ]
    
    # Count keyword occurrences
    user_score = sum(1 for kw in USER_KEYWORDS if kw in ql)
    book_score = sum(1 for kw in BOOK_KEYWORDS if kw in ql)
    
    # DELETE USER intent
    if is_delete and user_score > 0:
        # Try to extract user identifier
        target = None
        # Look for patterns like "delete user1", "remove User1", etc.
        match = re.search(r'\b(?:delete|remove|erase)\s+(?:user\s+)?([a-zA-Z0-9_@.-]+)', ql, re.I)
        if match:
            target = match.group(1)
        return {"intent": "delete_user", "target": target}
    
    # DELETE BOOK intent
    if is_delete and (book_score > 0 or user_score == 0):
        # Try to extract book title
        target = None
        # Remove common delete phrases to extract title
        title_candidate = ql
        for phrase in ["delete", "remove", "erase", "the book", "book", "from database", "from the database"]:
            title_candidate = title_candidate.replace(phrase, " ")
        target = title_candidate.strip()
        return {"intent": "delete_book", "target": target}
    
    # USER QUERY intent (higher user keyword score)
    if user_score > book_score:
        return {"intent": "user_query"}
    
    # BOOK QUERY intent (higher book keyword score or default)
    if book_score > 0:
        return {"intent": "book_query"}
    
    # Check for database-related queries without specific context
    DB_GENERAL_KEYWORDS = ["table", "database", "db", "show", "list", "all", "everything"]
    if any(kw in ql for kw in DB_GENERAL_KEYWORDS):
        # If "users" mentioned anywhere, prioritize user query
        if "user" in ql:
            return {"intent": "user_query"}
        # Otherwise could be book query
        return {"intent": "book_query"}
    
    # Default: treat as book query (for backward compatibility)
    return {"intent": "book_query"}

# ----------------------- LLM Helpers -----------------------
def llm_text(prompt: str) -> str:
    try:
        r = requests.post(LLM_API, json={"prompt": prompt, "mode": "text"}, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return (r.json().get("text") or "").strip()
    except Exception:
        logger.exception("LLM text call failed")
        return "I'm BookShelf-AI. I can help with user and book queries from our database."

def llm_sql(prompt: str) -> str:
    try:
        r = requests.post(LLM_API, json={"prompt": prompt, "mode": "sql"}, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        return (r.json().get("sql") or "").strip()
    except Exception:
        logger.exception("LLM SQL call failed")
        return ""

def generate_sql(query: str, schema_text: str, allow_modify: bool = False) -> Optional[str]:
    allowed_operations = "SELECT" if not allow_modify else "SELECT, INSERT, UPDATE, DELETE"
    prompt = f"""
You are a text-to-SQL assistant for a SQLite database.

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

# ==================== MAIN SEARCH ENDPOINT (FIXED) ====================
@app.route("/search", methods=["POST"])
def search():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    user_id = data.get("user_id")

    if not query:
        return jsonify({"error": "Empty query"}), 400

    # Detect intent
    intent_result = detect_intent(query)
    intent = intent_result["intent"]
    target = intent_result.get("target")
    
    logger.info(f"Intent detected: {intent} | Target: {target} | Query: {query}")

    schema = get_db_schema()
    schema_text = schema_as_text(schema)

    # ==================== CHITCHAT ====================
    if intent == "chitchat":
        answer = llm_text(f"You are BookShelf-AI, a friendly assistant. Respond to: {query}")
        return jsonify({
            "results": [],
            "generated_sql": "",
            "answer": answer,
            "intent": "chitchat"
        })

    # ==================== LIST ALL BOOKS ====================
    if intent == "list_all_books":
        # Get all books from MCP registry
        try:
            mcp_resp = requests.get(f"{MCP_API}/mcp/list_books", timeout=10)
            if mcp_resp.ok:
                books = mcp_resp.json().get("books", [])
                
                if len(books) == 0:
                    return jsonify({
                        "results": [],
                        "generated_sql": "",
                        "answer": "No books are currently uploaded to the database.",
                        "intent": "list_all_books"
                    })
                
                # Format book list for display
                answer = f"Here are all {len(books)} books in the database:\n\n"
                for idx, book in enumerate(books, 1):
                    answer += f"**{idx}. {book.get('title', 'Untitled')}**\n"
                    answer += f"   - Author: {book.get('author', 'Unknown')}\n"
                    if book.get('genre'):
                        answer += f"   - Genre: {book.get('genre')}\n"
                    answer += f"   - Chunks indexed: {book.get('vector_count', 0)}\n"
                    if book.get('filename'):
                        answer += f"   - Filename: {book.get('filename')}\n"
                    answer += "\n"
                
                return jsonify({
                    "results": books,
                    "generated_sql": "",
                    "answer": answer,
                    "intent": "list_all_books"
                })
            else:
                return jsonify({
                    "results": [],
                    "generated_sql": "",
                    "answer": "Failed to fetch books from the database.",
                    "intent": "list_all_books_error"
                }), 500
        except Exception as e:
            logger.exception("Error fetching all books from MCP")
            return jsonify({
                "results": [],
                "generated_sql": "",
                "answer": f"Error fetching books: {str(e)}",
                "intent": "list_all_books_error"
            }), 500

    # ==================== DELETE USER ====================
    if intent == "delete_user":
        # Generate DELETE SQL for users table
        sql = generate_sql(query, schema_text, allow_modify=True)
        
        if not sql or not sql.strip().lower().startswith("delete"):
            return jsonify({
                "results": [{"error": "Could not generate valid DELETE statement for user"}],
                "generated_sql": sql or "",
                "answer": "I couldn't understand which user to delete. Please specify the username, email, or user ID.",
                "intent": "delete_user_failed"
            }), 400

        # Ensure it's targeting the users table
        if "users" not in sql.lower():
            return jsonify({
                "results": [{"error": "SQL doesn't target users table"}],
                "generated_sql": sql,
                "answer": "The generated SQL doesn't target the users table. Please try again.",
                "intent": "delete_user_rejected"
            }), 400

        try:
            affected_rows = run_sql_modify(sql)
            answer = f"Successfully deleted {affected_rows} user(s) from the database."
            logger.info(f"Deleted {affected_rows} user(s) with SQL: {sql}")
            return jsonify({
                "results": [{"affected_rows": affected_rows}],
                "generated_sql": sql,
                "answer": answer,
                "intent": "delete_user_success"
            })
        except Exception as e:
            logger.exception("Error executing delete user SQL")
            return jsonify({
                "results": [{"error": str(e)}],
                "generated_sql": sql,
                "answer": f"Error deleting user: {str(e)}",
                "intent": "delete_user_error"
            }), 500

    # ==================== DELETE BOOK ====================
    if intent == "delete_book":
        # Try to delete from MCP first (vector database)
        try:
            # Get list of books from MCP
            mcp_resp = requests.get(f"{MCP_API}/mcp/list_books", timeout=10)
            if mcp_resp.ok:
                books = mcp_resp.json().get("books", [])
                
                # Find matching book
                target_lower = (target or "").lower()
                matched_book = None
                
                for book in books:
                    title = (book.get("title") or "").lower()
                    if target_lower in title or title in target_lower:
                        matched_book = book
                        break
                
                if matched_book:
                    # Delete from MCP
                    book_id = matched_book.get("book_id")
                    del_resp = requests.post(f"{MCP_API}/mcp/delete_book", json={"book_id": book_id}, timeout=30)
                    
                    if del_resp.ok:
                        return jsonify({
                            "results": [{"deleted": matched_book}],
                            "generated_sql": "",
                            "answer": f"Successfully deleted '{matched_book.get('title')}' by {matched_book.get('author')} from the vector database.",
                            "intent": "delete_book_success"
                        })
                    else:
                        return jsonify({
                            "results": [{"error": del_resp.text}],
                            "generated_sql": "",
                            "answer": f"Failed to delete book from MCP: {del_resp.text}",
                            "intent": "delete_book_error"
                        }), 500
                else:
                    return jsonify({
                        "results": [{"info": "Book not found in vector database"}],
                        "generated_sql": "",
                        "answer": f"Could not find a book matching '{target}' in the vector database.",
                        "intent": "delete_book_not_found"
                    }), 404
        except Exception as e:
            logger.exception("Error deleting book from MCP")
            return jsonify({
                "results": [{"error": str(e)}],
                "generated_sql": "",
                "answer": f"Error deleting book: {str(e)}",
                "intent": "delete_book_error"
            }), 500

    # ==================== USER QUERY (SQLite) ====================
    if intent == "user_query":
        sql = generate_sql(query, schema_text, allow_modify=False)
        
        if not sql:
            return jsonify({
                "results": [{"info": "Could not generate SQL for user query"}],
                "generated_sql": "",
                "answer": "I couldn't generate a valid SQL query for your request. Try asking about specific users by username, email, or role.",
                "intent": "user_query_failed"
            })

        if not sql.strip().lower().startswith("select"):
            return jsonify({
                "results": [{"error": "Only SELECT allowed for user queries"}],
                "generated_sql": sql,
                "answer": "For safety, only read-only SELECT queries are allowed.",
                "intent": "user_query_rejected"
            }), 400

        try:
            rows = run_sql_select(sql)
            answer = summarize_results(rows, query)
            logger.info(f"User query returned {len(rows)} rows")
            return jsonify({
                "results": rows,
                "generated_sql": sql,
                "answer": answer,
                "intent": "user_query"
            })
        except Exception as e:
            logger.exception("Error running user query SQL")
            return jsonify({
                "results": [{"error": str(e)}],
                "generated_sql": sql,
                "answer": f"Error executing query: {str(e)}",
                "intent": "user_query_error"
            }), 500

    # ==================== BOOK QUERY (MCP/Vector DB) ====================
    if intent == "book_query":
        # Try MCP RAG search first
        try:
            rag_resp = requests.post(f"{MCP_API}/mcp/search", json={
                "query": query,
                "user_id": user_id
            }, timeout=20)
            if rag_resp.ok:
                rag_data = rag_resp.json()
                if rag_data.get("answer") or rag_data.get("results"):
                    return jsonify(rag_data)
        except Exception as e:
            logger.exception("MCP search failed, falling back to SQL")

        # Fallback to SQL for books table
        sql = generate_sql(query, schema_text, allow_modify=False)
        if not sql:
            answer = llm_text(f"The user asked: {query}\nWe could not find relevant information. Suggest asking about books by title, author, or genre.")
            return jsonify({
                "results": [{"info": "No SQL generated"}],
                "generated_sql": "",
                "answer": answer,
                "intent": "book_query_failed"
            })

        if not sql.strip().lower().startswith("select"):
            return jsonify({
                "results": [{"error": "Only SELECT allowed"}],
                "generated_sql": sql,
                "answer": "Only read-only queries are allowed.",
                "intent": "book_query_rejected"
            }), 400

        try:
            rows = run_sql_select(sql)
            answer = summarize_results(rows, query)
            return jsonify({
                "results": rows,
                "generated_sql": sql,
                "answer": answer,
                "intent": "book_query"
            })
        except Exception as e:
            logger.exception("Error running book query SQL")
            return jsonify({
                "results": [{"error": str(e)}],
                "generated_sql": sql,
                "answer": f"Error: {str(e)}",
                "intent": "book_query_error"
            }), 500

    # Default fallback
    return jsonify({
        "results": [],
        "generated_sql": "",
        "answer": "I didn't understand your request. Please ask about users or books in the database.",
        "intent": "unknown"
    })

# ==================== ADMIN ENDPOINTS ====================
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

# ==================== MCP / INGEST ====================
@app.route("/ingest", methods=["POST"])
def ingest():
    user_id = request.form.get("user_id")
    title = request.form.get("title")
    author = request.form.get("author")
    book_id = request.form.get("book_id")
    pdf = request.files.get("pdf")

    if not user_id or not title or not author or not pdf:
        return jsonify({"error": "Missing Required Fields: user_id, title, author, pdf"}), 400

    try:
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
    app.run(host="0.0.0.0", port=BACKEND_PORT, debug=False)