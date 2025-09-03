from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import requests
import os
import re

app = Flask(__name__)
CORS(app)

DB_PATH = "database.db"
LLM_API = os.getenv("LLM_API", "http://127.0.0.1:5000/query")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ==================== SIGNUP ====================
@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("INSERT INTO users (username, email, password, phone_number) VALUES (?,?,?,?)",
                (data['username'], data['email'], data['password'], data['phone']))
    conn.commit()
    conn.close()

    return jsonify({"message": "User Created"}), 201


# ==================== LOGIN ====================
@app.route("/login", methods=['POST'])
def login():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email=? AND password=?", (data['email'], data['password']))
    user = cur.fetchone()
    conn.close()

    if user:
        return jsonify({"message": "Login Successful"})
    return jsonify({"error": "Invalid Credentials"}), 401


# ==================== SEARCH ====================
def get_db_schema():
    """Extracts current schema from SQLite database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cur.fetchall()

    schema = {}
    for (table,) in tables:
        cur.execute(f"PRAGMA table_info({table});")
        cols = cur.fetchall()
        schema[table] = [col[1] for col in cols]  # col[1] = column name
    conn.close()
    return schema


@app.route("/search", methods=["POST"])
def search():
    query = request.json.get("query")
    schema = get_db_schema()

    # Build schema description dynamically
    schema_text = "\n".join([f"- {table}({', '.join(cols)})" for table, cols in schema.items()])

    # Step 1: Ask LLM for SQL
    response = requests.post(LLM_API, json={
        "prompt": f"""
        You are a text-to-SQL assistant.
        The user asked: {query}

        Database schema:
        {schema_text}

        Rules:
        - Only output a valid SQLite SQL query.
        - Do not explain or add text.
        - Do not use information_schema (SQLite doesn’t support it).
        - Always match exact table/column names.
        """,
        "mode": "sql"
    })
    raw_sql = response.json().get("sql", "")

    # Extract SQL only
    match = re.search(r"(SELECT|DELETE|DROP|UPDATE|INSERT).*", raw_sql, re.IGNORECASE)
    sql_query = match.group(0).strip() if match else None

    conn = get_db_connection()
    cur = conn.cursor()
    results = []
    ai_answer = ""

    try:
        if sql_query:
            cur.execute(sql_query)

            if sql_query.strip().lower().startswith("select"):
                rows = cur.fetchall()
                results = [dict(zip([col[0] for col in cur.description], row)) for row in rows]

                # Step 2: Ask LLM for human-friendly answer
                if results:
                    llm_summary = requests.post(LLM_API, json={
                        "prompt": f"""
                        The user asked: {query}
                        Database returned: {results}

                        Write a clean, human-friendly answer (like ChatGPT).
                        Only output natural text, not SQL.
                        """,
                        "mode": "text"
                    })
                    ai_answer = llm_summary.json().get("text", "").strip()
            else:
                conn.commit()
                results = [{"status": "Query executed successfully"}]
                ai_answer = "✅ Query executed successfully."
        else:
            results = [{"error": "No valid SQL generated"}]
            ai_answer = "⚠️ Could not generate SQL for your request."

    except Exception as e:
        results = [{"error": str(e)}]
        ai_answer = f"⚠️ Error executing query: {str(e)}"

    finally:
        conn.close()

    return jsonify({
        "generated_sql": sql_query or raw_sql,
        "results": results,
        "answer": ai_answer
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
