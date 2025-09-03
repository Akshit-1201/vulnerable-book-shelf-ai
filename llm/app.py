from flask import Flask, request, jsonify
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

app = Flask(__name__)

# Load Hugging Face text2sql model
# MODEL_NAME = "mrm8488/text2sql-t5-small"
# MODEL_NAME = "dbernsohn/t5_wikisql_SQL2en"

MODEL_NAME = "Qwen/Qwen1.5-1.8B"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    device_map="auto"
    )

@app.route("/query", methods=["POST"])
def query():
    prompt = request.json.get("prompt", "")
    full_prompt = f"Translate to SQL: {prompt}\nSQL:"
    
    inputs = tokenizer(full_prompt, return_tensors="pt").to(model.device)
    outputs = model.generate(
        **inputs,
        max_new_tokens=128,
        do_sample=True,
        temperature=0.7,
        top_p=0.95
    )
    
    text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    # Extract only SQL starting from the first SELECT
    if "SELECT" in text.upper():
        sql = text[text.upper().index("SELECT"):]
    else:
        sql = f"SELECT * FROM books WHERE title LIKE '%{prompt}%' OR author LIKE '%{prompt}%';"
        
    return jsonify({"sql": sql})
    
    # # Convert NL to SQL Using Models
    # inputs = tokenizer.encode(prompt, return_tensors='pt', truncation=True)
    # outputs = model.generate(inputs, max_length=128)
    # sql = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    # # By Design: Do not sanitize the Output
    # return jsonify({"sql": sql})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)