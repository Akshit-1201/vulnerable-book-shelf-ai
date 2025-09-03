from flask import Flask, request, jsonify
from dotenv import load_dotenv
import os
from openai import OpenAI

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)

# 🔑 Configure OpenAI client
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("❌ OPENAI_API_KEY not set in .env file")

client = OpenAI(api_key=OPENAI_API_KEY)

@app.route("/query", methods=["POST"])
def query():
    prompt = request.json.get("prompt", "")

    # Strong instruction to only return SQL
    full_prompt = f"""
    Convert the following user request into a valid SQLite SQL query.
    Only output SQL code, nothing else.

    Request: "{prompt}"
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini-search-preview-2025-03-11",
        messages=[
            {"role": "system", "content": "You are a SQL generator. Always return only SQL, no explanations."},
            {"role": "user", "content": full_prompt}
        ],
        max_tokens=200,
        temperature=0.3
    )

    sql = response.choices[0].message.content.strip()

    return jsonify({"sql": sql})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
