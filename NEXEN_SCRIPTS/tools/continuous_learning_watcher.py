import os
import time
import json
import logging
from datetime import datetime
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("Please install watchdog: pip install watchdog")
    exit(1)

# Configuration
VAULT_DIR = r"H:\NEXEN\obsidian-vault"  # Update this to your actual vault path
MEMORY_FILE = r"H:\NEXEN_MEMORY\Marvin_Brain_Index.json"
LOG_FILE = r"H:\NEXEN_LOGS\continuous_learning.log"

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, 
                    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

class VaultWatcherHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.ensure_memory_file()

    def ensure_memory_file(self):
        os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
        if not os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
                json.dump({"knowledge_chunks": []}, f, indent=4)

    def process_file(self, file_path):
        if not file_path.endswith(('.md', '.pdf', '.txt')):
            return

        filename = os.path.basename(file_path)
        logging.info(f"New or modified knowledge detected: {filename}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Ingesting: {filename}")

        # In a full implementation, you would parse PDFs or chunk Markdown here.
        # For now, we log its metadata to Marvin's Brain Index.
        
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                brain = json.load(f)
        except Exception:
            brain = {"knowledge_chunks": []}

        # Check if file is already indexed, update timestamp
        indexed = False
        for chunk in brain["knowledge_chunks"]:
            if chunk.get("file_path") == file_path:
                chunk["last_updated"] = datetime.now().isoformat()
                indexed = True
                break
        
        if not indexed:
            brain["knowledge_chunks"].append({
                "file_path": file_path,
                "filename": filename,
                "type": "obsidian_note" if file_path.endswith('.md') else "document",
                "ingested_at": datetime.now().isoformat(),
                "status": "ready_for_marvin_review"
            })

        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(brain, f, indent=4)
            
        logging.info(f"Successfully updated Marvin's Brain with {filename}")

    def on_created(self, event):
        if not event.is_directory:
            self.process_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.process_file(event.src_path)

def start_watching():
    os.makedirs(VAULT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    
    event_handler = VaultWatcherHandler()
    observer = Observer()
    observer.schedule(event_handler, VAULT_DIR, recursive=True)
    
    print(f"Starting Continuous Learning Pipeline...")
    print(f"Watching Vault: {VAULT_DIR}")
    print(f"Feeding to Brain: {MEMORY_FILE}")
    logging.info("Continuous Learning Pipeline Started.")
    
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("Pipeline Stopped.")
    observer.join()

if __name__ == "__main__":
    start_watching()
