import os
import glob
import json
import subprocess
from pathlib import Path
from datetime import datetime

def extract_conversations():
    brain_dir = r"%USERPROFILE%\.gemini\antigravity\brain"
    conversations = []
    
    # Find all transcript files
    transcripts = glob.glob(os.path.join(brain_dir, "**", "transcript.jsonl"), recursive=True)
    
    for transcript in transcripts:
        conv_id = Path(transcript).parent.parent.parent.name
        messages = []
        try:
            with open(transcript, 'r', encoding='utf-8') as f:
                for line in f:
                    data = json.loads(line)
                    # We only care about User inputs and Planner Responses for context
                    if data.get('type') == 'USER_INPUT':
                        messages.append(f"**USER:** {data.get('content', '')}")
                    elif data.get('type') == 'PLANNER_RESPONSE':
                        # Filter out excessive tool calls, just get the text
                        content = data.get('content', '')
                        if content:
                            messages.append(f"**AI:** {content}")
                            
            if messages:
                conversations.append({
                    "id": conv_id,
                    "messages": messages
                })
        except Exception as e:
            pass
            
    return conversations

def write_to_obsidian(conversations):
    # Target the recovered obsidian vault
    obsidian_dir = Path(r"H:\NEXEN\obsidian\NEXEN-Recovered-20261005")
    if not obsidian_dir.exists():
        obsidian_dir = Path(r"H:\NEXEN\obsidian")
        
    date_str = datetime.now().strftime("%Y-%m-%d")
    file_name = f"CONTEXT_AGENT_DUMP_{date_str}.md"
    file_path = obsidian_dir / file_name
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(f"# Context Agent: Master Conversation Dump\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Pending 'Things To Do' for Owner\n")
        f.write("- [ ] Review 3000-Link Scrape Results on Desktop (`Scrape_Results_3000_VIRAL`)\n")
        f.write("- [ ] Review TricorderKit & Swarm Local Executions\n")
        f.write("- [ ] Close this Notepad file to confirm receipt.\n\n")
        
        f.write("---\n\n")
        
        for conv in conversations[-5:]: # Get latest 5 conversations to avoid massive file
            f.write(f"### Conversation ID: {conv['id']}\n")
            for msg in conv['messages']:
                f.write(f"{msg}\n\n")
            f.write("---\n")
            
    return file_path

def main():
    print("Context Agent: Extracting all visible conversations...")
    conversations = extract_conversations()
    
    print("Context Agent: Writing to Obsidian Vault...")
    obsidian_file = write_to_obsidian(conversations)
    
    print(f"Context Agent: Leaving file open for Owner at {obsidian_file}")
    # Open the file in notepad. The script blocks until notepad is closed.
    subprocess.call(['notepad.exe', str(obsidian_file)])
    
    # Once closed, print confirmation
    print("Context Agent: Notepad closed. Receipt confirmed by Owner.")

if __name__ == "__main__":
    main()
