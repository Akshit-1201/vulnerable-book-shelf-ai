from flask import Flask, request, jsonify
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

app = Flask(__name__)

# Get API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("❌ GEMINI_API_KEY not found in .env file")

genai.configure(api_key=GEMINI_API_KEY)

text_model = genai.GenerativeModel("gemini-2.5-flash")
embedding_model = "gemini-embedding-001"


@app.route("/query", methods=["POST"])
def query():
    """Handles both SQL generation and natural text responses."""
    prompt = request.json.get("prompt", "")
    mode = request.json.get("mode", "sql")

    response = text_model.generate_content(prompt)
    text = response.text.strip()
    
    if mode == "sql":
        return jsonify({"sql": text})
    return jsonify({"text": text})

@app.route("/embed", methods=["POST"])
def embed():
    '''
    Generates Embeddings of the PDF content
    '''
    data = request.get_json(force=True)
    texts = data.get("texts") or [data.get("text")]

    if not texts or not isinstance(texts, list):
        return jsonify({
            "error": "Provide 'text' or 'texts' as list/string"
        }), 400

    try:
        result = genai.embed_content(
            model=embedding_model,
            content=texts,
            task_types="retrieval_document"
        )

        embeddings = result.get("embeddings") or [result["embedding"]]

        return jsonify({
            "embeddings": embeddings
        })

    except Exception as e:
        return jsonify({
            "error": f"Embedding Model Error: {str(e)}"
        }), 500


@app.route("/")
def root():
    return jsonify({
        "message": "LLM Service is running with Gemini Models"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
