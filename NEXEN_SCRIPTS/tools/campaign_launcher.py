import sys
import subprocess
from datetime import datetime

BRIDGE_SCRIPT = r"H:\NEXEN\tools\worker-bridge\nexen_bridge.py"

def launch_campaign(target_entity, campaign_type):
    print("==================================================")
    print(f"🚀 INITIATING NEXEN CAMPAIGN RUN")
    print(f"🎯 Target Entity: {target_entity}")
    print(f"📊 Campaign Type: {campaign_type}")
    print("==================================================")
    
    prompt = f"EXECUTE {campaign_type.upper()} CAMPAIGN FOR {target_entity.upper()}. Generate content, format hooks, and prepare for distribution."
    
    # Dispatch to the Hustle Agent (which runs the Virality Engine)
    subprocess.run([
        "python", BRIDGE_SCRIPT, "send",
        "--ticket", f"CAMPAIGN-{target_entity.replace(' ', '')}",
        "--to", "Hustle Agent",
        "--prompt", prompt,
        "--source", "campaign_launcher",
        "--context", f"ENTITY:{target_entity}|TYPE:{campaign_type}"
    ])
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Campaign dispatched to the Swarm Bridge. The Virality Engine is spooling up.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python launch_campaign.py <Target Entity> <Campaign Type>")
        print("Example: python launch_campaign.py 'Lumipaw' 'TikTok Shop Setup'")
    else:
        launch_campaign(sys.argv[1], sys.argv[2])
