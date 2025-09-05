from flask import Flask, request, jsonify
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

app = Flask(__name__)

# Get API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY_2")
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY not found in .env file")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")


@app.route("/query", methods=["POST"])
def query():
    """Handles both SQL generation and natural text responses."""
    prompt = request.json.get("prompt", "")
    mode = request.json.get("mode", "sql")  # default to sql mode

    # Run Gemini
    response = model.generate_content(prompt)
    text = response.text.strip()

    # SQL mode → only return SQL snippet
    if mode == "sql":
        return jsonify({"sql": text})

    # Summary/answer mode → return natural text
    return jsonify({"text": text})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
