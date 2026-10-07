import os
import sys
import json
import urllib.request
import urllib.error

# Add parent directory to path to allow imports if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from workflow_tools import WORKFLOW_TOOLS, TOOL_FUNCTIONS

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_MASTER = "nexen-workflow-master"
MODEL_LITE = "nexen-workflow-3b"
OUTPUT_DIR = r"H:\NEXEN\workflows\output"

def check_model_availability(model_name):
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            models = [m["name"] for m in data.get("models", [])]
            return any(model_name in m for m in models)
    except Exception:
        return False

def chat_with_tools(prompt, model_name=MODEL_MASTER):
    if not check_model_availability(model_name):
        print(f"Model {model_name} not available, falling back to {MODEL_LITE}...")
        model_name = MODEL_LITE
    
    messages = [{"role": "user", "content": prompt}]
    
    payload = {
        "model": model_name,
        "messages": messages,
        "tools": WORKFLOW_TOOLS,
        "stream": False
    }
    
    try:
        req = urllib.request.Request(
            OLLAMA_URL, 
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            
            message = result.get('message', {})
            if 'tool_calls' in message:
                for tool_call in message['tool_calls']:
                    func_name = tool_call['function']['name']
                    args = tool_call['function']['arguments']
                    print(f"Calling tool: {func_name} with args: {args}")
                    
                    if func_name in TOOL_FUNCTIONS:
                        tool_result = TOOL_FUNCTIONS[func_name](**args)
                        print(f"Tool Result:\n{tool_result}")
                        
                        # Save result if it's a workflow
                        if func_name == "create_n8n_workflow":
                            os.makedirs(OUTPUT_DIR, exist_ok=True)
                            out_file = os.path.join(OUTPUT_DIR, f"{args.get('name', 'workflow')}.json")
                            with open(out_file, 'w') as f:
                                f.write(tool_result)
                            print(f"Saved workflow to {out_file}")
            else:
                print("Model Response:", message.get('content', ''))
                
    except urllib.error.URLError as e:
        print(f"Error communicating with Ollama: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
        chat_with_tools(prompt)
    else:
        print("Usage: python workflow_agent.py \"<your prompt here>\"")
