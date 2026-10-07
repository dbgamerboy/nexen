import os, subprocess, re

LEADS_FILE = r"H:\NEXEN\operations\money\sources\LEADS-2026-09-26.md"
BRIDGE_SCRIPT = r"H:\NEXEN\tools\worker-bridge\nexen_bridge.py"

def disperse():
    print("🚀 DISPERSING AGENTS ACROSS ALL HUSTLES...")
    if not os.path.exists(LEADS_FILE):
        print("No leads file found.")
        return
        
    with open(LEADS_FILE, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Find all hustle sections starting with "## "
    hustles = re.findall(r"## (.*?)\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    
    for title, details in hustles:
        if "Closed" in title or "closed" in title.lower():
            continue
            
        print(f"\nTargeting Hustle: {title.strip()}")
        prompt = f"Analyze hustle and draft execution plan: {title.strip()}"
        
        # Dispatch to the Hustle Agent via Bridge
        subprocess.run([
            "python", BRIDGE_SCRIPT, "send",
            "--ticket", "MONEY-LOOP",
            "--to", "Hustle Agent",
            "--prompt", prompt,
            "--source", "disperse_script",
            "--context", "LEADS.md"
        ])
        print("✅ Dispatched to Swarm Queue.")

if __name__ == "__main__":
    disperse()
