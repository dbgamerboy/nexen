import os
import time
import json
import logging
import requests
from datetime import datetime

# Swarm Configuration
MEMORY_FILE = r"H:\NEXEN_MEMORY\Marvin_Brain_Index.json"
SWARM_QUEUE = r"H:\NEXEN_MEMORY\Swarm_Task_Queue.json"
LOG_FILE = r"H:\NEXEN_LOGS\marvin_swarm_orchestrator.log"

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, 
                    format='%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# OpenRouter Configuration
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

def ensure_queue():
    os.makedirs(os.path.dirname(SWARM_QUEUE), exist_ok=True)
    if not os.path.exists(SWARM_QUEUE):
        with open(SWARM_QUEUE, 'w', encoding='utf-8') as f:
            json.dump({"tasks": []}, f, indent=4)

def load_json(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

class SubAgents:
    """Mock implementations of the Swarm Sub-Agents."""
    @staticmethod
    def vault_agent(task_data):
        msg = "Analysis complete. Context stored in vector memory."
        logging.info(f"[Vault Agent] {msg}")
        return msg

    @staticmethod
    def email_agent(task_data):
        msg = "Draft saved."
        logging.info(f"[Email Agent] {msg}")
        return msg

    @staticmethod
    def calendar_agent(task_data):
        msg = "Event created."
        logging.info(f"[Calendar Agent] {msg}")
        return msg

class MarvinExecutive:
    """The Main Orchestrator"""
    def __init__(self):
        self.last_memory_check = 0

    def get_company_context(self):
        master_prompt_path = r"H:\NEXEN\obsidian\NEXEN-Working\00-Control\NEXEN-MASTER-PROMPT.md"
        try:
            with open(master_prompt_path, 'r', encoding='utf-8') as f:
                content = f.read(1500) # Grab the first chunk of the master prompt
            return f"\nCOMPANY CONTEXT:\n{content}\n"
        except Exception:
            return ""

    def call_llm(self, user_content):
        logging.info("Routing to Local Ollama Model...")
        company_info = self.get_company_context()
        
        system_prompt = (
            f"Today's date is: {datetime.now().strftime('%Y-%m-%d')}.\n"
            "You are MARVIN, the Executive Orchestrator. "
            "You don't need to take action. You don't need to send emails. "
            "You just need to delegate the task to the right tool/agent.\n"
            f"{company_info}"
            "Respond ONLY with the exact name of the sub-agent to route to from this list: "
            "[Vault Agent, Email Agent, Calendar Agent, Hustle Agent, FBA Agent, Scheduler Agent, Tracker Agent, SMS Agent, Archivist Agent, Data Engineer Agent]."
        )

        try:
            # We assume Ollama is running a small fast model like llama3 or mistral
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3",  # Switch this if using a different local model name in Ollama
                    "system": system_prompt,
                    "prompt": f"New knowledge arrived: {user_content}. Which agent should process this?",
                    "stream": False
                },
                timeout=15
            )
            data = response.json()
            if "response" in data:
                return data["response"].strip()
        except requests.exceptions.RequestException as e:
            logging.error(f"Local LLM Call Failed (Is Ollama running?): {e}")
        
        return "Vault Agent"

    def evaluate_new_knowledge(self):
        if not os.path.exists(MEMORY_FILE):
            return

        mtime = os.path.getmtime(MEMORY_FILE)
        if mtime <= self.last_memory_check:
            return

        self.last_memory_check = mtime
        brain = load_json(MEMORY_FILE)
        chunks = brain.get("knowledge_chunks", [])
        
        updated = False
        for chunk in chunks:
            if chunk.get("status") == "ready_for_marvin_review":
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🧠 MARVIN: Analyzing intent for {chunk.get('filename')} via LLM...")
                
                # 1. Ask the LLM Orchestrator to decide
                target_agent = self.call_llm(chunk.get("filename"))
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧠 MARVIN: Routing to -> {target_agent}")
                
                # 2. Delegate to the Agent
                self.route_to_agent(target_agent, chunk)
                
                chunk["status"] = "studied_by_swarm"
                updated = True
        
        if updated:
            save_json(MEMORY_FILE, brain)

    def route_to_agent(self, agent_name, task_data):
        import subprocess
        bridge_script = r"H:\NEXEN\tools\worker-bridge\nexen_bridge.py"
        
        # Extract exact target name
        target = "Vault Agent"
        for possible_agent in ["Email Agent", "Calendar Agent", "Hustle Agent", "FBA Agent", "Scheduler Agent", "Tracker Agent", "SMS Agent", "Archivist Agent", "Data Engineer Agent"]:
            if possible_agent in agent_name:
                target = possible_agent
                break

        prompt = f"Process new knowledge: {task_data.get('filename')}"
        context = task_data.get('file_path', 'unknown')
        
        try:
            result = subprocess.run(
                ["python", bridge_script, "send", "--ticket", "MARVIN-SWARM", "--to", target, "--prompt", prompt, "--source", "marvin_orchestrator", "--context", context],
                capture_output=True, text=True, check=True
            )
            job_id = result.stdout.strip()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🚀 Dispatched to Bridge: {target} (Job: {job_id})")
            logging.info(f"Dispatched via bridge: {job_id}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Bridge dispatch failed: {e}")
            
def start_autonomous_loop():
    print("==================================================")
    print("🤖 MARVIN SWARM ORCHESTRATOR - ONLINE (NEXEN BRIDGE)")
    print("==================================================")
    ensure_queue()
    marvin = MarvinExecutive()
    
    try:
        while True:
            marvin.evaluate_new_knowledge()
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nSwarm Orchestrator Offline.")

if __name__ == "__main__":
    start_autonomous_loop()
