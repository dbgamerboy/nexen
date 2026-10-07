import os
import json
import requests
import datetime

DB_FILE = r"H:\NEXEN_MEMORY\enterprise_rag_db.json"
OLLAMA_URL = "http://localhost:11434/api/generate"

def init_db():
    if not os.path.exists(DB_FILE):
        os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump({"documents": []}, f)

def generate_tags(content_chunk):
    # Ask local LLM to generate 3 tags
    prompt = f"Analyze this text and provide exactly 3 comma-separated tags that categorize it. No explanation.\n\nTEXT:\n{content_chunk[:500]}"
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": "llama3",
            "prompt": prompt,
            "stream": False
        }, timeout=10)
        if resp.status_code == 200:
            return [t.strip() for t in resp.json().get("response", "").split(",") if t.strip()]
    except:
        pass
    return ["untagged"]

def chunk_text(text, chunk_size=1500):
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append(text[i:i+chunk_size])
    return chunks

def process_file(filepath):
    init_db()
    if not os.path.exists(filepath):
        return
        
    print(f"🧬 DATA ENGINEER AGENT: Processing {filepath}")
    
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    chunks = chunk_text(content)
    
    # Generate tags from the first chunk
    tags = generate_tags(chunks[0] if chunks else "")
    
    with open(DB_FILE, 'r+', encoding='utf-8') as f:
        db = json.load(f)
        
        doc_entry = {
            "filepath": filepath,
            "filename": os.path.basename(filepath),
            "ingested_at": datetime.datetime.now().isoformat(),
            "tags": tags,
            "chunk_count": len(chunks),
            "chunks": chunks
        }
        
        # Remove old version if exists
        db["documents"] = [d for d in db["documents"] if d["filepath"] != filepath]
        db["documents"].append(doc_entry)
        
        f.seek(0)
        json.dump(db, f, indent=2)
        f.truncate()
        
    print(f"✅ Embedded {len(chunks)} chunks with tags {tags} into Enterprise RAG DB.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        process_file(sys.argv[1])
