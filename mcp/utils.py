import os
import uuid
import json 
import math 
from pdfminer.high_level import extract_text
from tqdm import tqdm

def ensure_dir(p):
    os.makedirs(p, exists_ok=True)

def extract_text_from_pdf(path: str) -> str:
    '''
    Use pdfminer to extract text from a PDF file.
    '''
    return extract_text(path) or ""

def chunk_text(text: str, chunk_size_chars: int = 1500, overlap_chars: int = 200):
    '''
    Naive text chunker based on characters. Returns list of dicts:
    [{"id": "<uuid>", "text": "...", "start": n, "end": m}, ...]
    '''
    if not text:
        return []
    
    chunks = []
    i=0
    n = len(text)
    
    while i<n:
        end = min(i+chunk_size_chars, n)
        chunk_text = text[i:end].strip()
        
        if chunk_text:
            chunks.append({
                "id": str(uuid.uuid4()),
                "text": chunk_text,
                "start": i,
                "end": end
            })
        # move by chunk_size - overlap
        i = end - overlap_chars if end - overlap_chars > i else end  
    
    return chunks

def safe_write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def safe_read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return default