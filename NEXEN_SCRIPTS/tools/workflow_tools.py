import json
import os

def create_n8n_workflow(name, nodes, connections):
    """Generates an n8n workflow JSON structure."""
    workflow = {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": {}
    }
    return json.dumps(workflow, indent=2)

def create_cron_schedule(name, expression, command):
    """Creates a scheduled task script based on a cron expression."""
    return json.dumps({"status": "success", "task": name, "schedule": expression, "command": command})

def create_webhook(name, url, method, headers):
    """Sets up a webhook listener definition."""
    return json.dumps({"status": "success", "webhook": name, "url": url, "method": method, "headers": headers})

def chain_apis(steps):
    """Chains multiple API calls with data passing."""
    return json.dumps({"status": "success", "chain_length": len(steps), "steps": steps})

def generate_automation_script(description):
    """Generates Python automation code from a description."""
    code = f"# Automation for: {description}\n# Generated script goes here\nprint('Running automation...')"
    return json.dumps({"status": "success", "code": code})

def validate_workflow(workflow_json):
    """Validates an n8n workflow structure."""
    try:
        data = json.loads(workflow_json)
        is_valid = "nodes" in data and "connections" in data
        return json.dumps({"valid": is_valid, "error": None if is_valid else "Missing nodes or connections"})
    except json.JSONDecodeError as e:
        return json.dumps({"valid": False, "error": str(e)})

def list_active_workflows():
    """Lists running automations (simulated)."""
    return json.dumps({"active_workflows": []})

def create_data_pipeline(source, transforms, destination):
    """Generates an ETL pipeline definition."""
    pipeline = {
        "source": source,
        "transforms": transforms,
        "destination": destination
    }
    return json.dumps({"status": "success", "pipeline": pipeline})

# Tools schema for Ollama
WORKFLOW_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_n8n_workflow",
            "description": "Generates n8n workflow JSON.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name"},
                    "nodes": {"type": "array", "items": {"type": "object"}, "description": "List of node objects"},
                    "connections": {"type": "object", "description": "Connection mapping"}
                },
                "required": ["name", "nodes", "connections"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_cron_schedule",
            "description": "Creates scheduled tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "expression": {"type": "string"},
                    "command": {"type": "string"}
                },
                "required": ["name", "expression", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_webhook",
            "description": "Sets up webhook listeners.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string"},
                    "method": {"type": "string"},
                    "headers": {"type": "object"}
                },
                "required": ["name", "url", "method", "headers"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "chain_apis",
            "description": "Chains multiple API calls with data passing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {"type": "array", "items": {"type": "object"}}
                },
                "required": ["steps"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_automation_script",
            "description": "Generates Python automation from description.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"}
                },
                "required": ["description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "validate_workflow",
            "description": "Validates n8n workflow structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_json": {"type": "string"}
                },
                "required": ["workflow_json"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_workflows",
            "description": "Lists running automations.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_data_pipeline",
            "description": "Generates an ETL pipeline definition.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "object"},
                    "transforms": {"type": "array", "items": {"type": "object"}},
                    "destination": {"type": "object"}
                },
                "required": ["source", "transforms", "destination"]
            }
        }
    }
]

TOOL_FUNCTIONS = {
    "create_n8n_workflow": create_n8n_workflow,
    "create_cron_schedule": create_cron_schedule,
    "create_webhook": create_webhook,
    "chain_apis": chain_apis,
    "generate_automation_script": generate_automation_script,
    "validate_workflow": validate_workflow,
    "list_active_workflows": list_active_workflows,
    "create_data_pipeline": create_data_pipeline
}
