import os
import time
import shutil
import logging
from pathlib import Path
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("Please install watchdog: pip install watchdog")
    exit(1)

# Configuration
WATCH_DIR = r"H:\\"
ARCHIVE_DIR = Path(r"H:\NEXEN_ARCHIVE")
LOG_FILE = r"H:\NEXEN_LOGS\spaghetti_watcher.log"

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, 
                    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

CATEGORIES = {
    "Installers": [".exe", ".msi"],
    "Books_and_Docs": [".epub", ".pdf", ".txt", ".csv", ".md"],
    "Media": [".mkv", ".mp4", ".mp3", ".jpg", ".png", ".zip"],
    "Scripts": [".ahk", ".ps1", ".cmd", ".bat"]
}

class SpaghettiWatcherHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        for cat in CATEGORIES.keys():
            (ARCHIVE_DIR / cat).mkdir(parents=True, exist_ok=True)
        (ARCHIVE_DIR / "Misc").mkdir(parents=True, exist_ok=True)

    def process_file(self, file_path):
        p = Path(file_path)
        if not p.is_file() or p.parent != Path(WATCH_DIR):
            return
            
        # Protect system/core files
        if "NEXEN" in p.name or "pagefile.sys" in p.name.lower() or "swapfile.sys" in p.name.lower():
            return
            
        ext = p.suffix.lower()
        target_folder = "Misc"
        
        for category, extensions in CATEGORIES.items():
            if ext in extensions:
                target_folder = category
                break
                
        destination = ARCHIVE_DIR / target_folder / p.name
        try:
            shutil.move(str(p), str(destination))
            print(f"[{time.strftime('%H:%M:%S')}] 🧹 Archivist Agent auto-moved spaghetti: {p.name} -> {target_folder}")
            logging.info(f"Auto-archived: {p.name} to {target_folder}")
        except Exception as e:
            pass

    def on_created(self, event):
        if not event.is_directory:
            # Short delay to ensure file is fully written before moving
            time.sleep(1)
            self.process_file(event.src_path)

def start_watching():
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    
    event_handler = SpaghettiWatcherHandler()
    observer = Observer()
    # Watch root non-recursively (recursive=False) so we only catch stray root spaghetti
    observer.schedule(event_handler, WATCH_DIR, recursive=False)
    
    print("==================================================")
    print("🧹 ARCHIVIST AGENT - SPAGHETTI WATCHER ONLINE")
    print(f"Monitoring {WATCH_DIR} for loose files...")
    print("==================================================")
    logging.info("Spaghetti Watcher Started.")
    
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("Watcher Stopped.")
    observer.join()

if __name__ == "__main__":
    start_watching()
