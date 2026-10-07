import os
import shutil
from pathlib import Path

SOURCE_DIR = Path("H:\\")
ARCHIVE_DIR = Path("H:\\NEXEN_ARCHIVE")

CATEGORIES = {
    "Installers": [".exe", ".msi"],
    "Books_and_Docs": [".epub", ".pdf", ".txt", ".csv", ".md"],
    "Media": [".mkv", ".mp4", ".mp3", ".jpg", ".png", ".zip"],
    "Scripts": [".ahk", ".ps1", ".cmd", ".bat"]
}

def clean_spaghetti():
    print("🧹 ARCHIVIST AGENT: Cleaning up spaghetti files in H:\\ root...")
    
    for category in CATEGORIES.keys():
        (ARCHIVE_DIR / category).mkdir(parents=True, exist_ok=True)
    (ARCHIVE_DIR / "Misc").mkdir(parents=True, exist_ok=True)

    moved_count = 0
    for file_path in SOURCE_DIR.iterdir():
        if not file_path.is_file():
            continue
            
        # Protect specific root files if needed
        if "NEXENhandoffs" in file_path.name:
            continue
            
        ext = file_path.suffix.lower()
        target_folder = "Misc"
        
        for category, extensions in CATEGORIES.items():
            if ext in extensions:
                target_folder = category
                break
                
        destination = ARCHIVE_DIR / target_folder / file_path.name
        try:
            shutil.move(str(file_path), str(destination))
            print(f"📦 Moved: {file_path.name} -> {target_folder}")
            moved_count += 1
        except Exception as e:
            print(f"❌ Failed to move {file_path.name}: {e}")

    print(f"✅ Archivist cleanup complete. Moved {moved_count} spaghetti files.")

if __name__ == "__main__":
    clean_spaghetti()
