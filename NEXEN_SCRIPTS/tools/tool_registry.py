import sys
from pathlib import Path
from typing import Dict, Any, List, Callable

NEXEN_ROOT = Path(r"H:\NEXEN")
sys.path.insert(0, str(NEXEN_ROOT / "tools"))

from computer_use_tools import TOOL_DEFINITIONS as CU_DEFS, TOOL_DISPATCH as CU_DISPATCH
from nexen_tool_agent import TOOL_DEFINITIONS as AGENT_DEFS, TOOL_DISPATCH as AGENT_DISPATCH

ALL_DEFINITIONS = AGENT_DEFS + CU_DEFS
TOOL_CATALOG = {**AGENT_DISPATCH, **CU_DISPATCH}

def get_all_tools() -> List[Dict[str, Any]]:
    """Return all available tool schemas."""
    return ALL_DEFINITIONS

def execute_tool(name: str, args: Dict[str, Any], model_name: str = "agent") -> Any:
    """Execute a tool by name with the given arguments and log its receipt."""
    import time
    from tool_receipt_logger import log_tool_receipt
    tool_fn = TOOL_CATALOG.get(name)
    if not tool_fn:
        res = {"status": "error", "error": f"Unknown tool: {name}"}
        log_tool_receipt(name, args, res, model=model_name, status="failed", duration_sec=0.0)
        return res
    start_time = time.time()
    try:
        res = tool_fn(**args)
        duration = time.time() - start_time
        log_tool_receipt(name, args, res, model=model_name, status="success", duration_sec=duration)
        return res
    except Exception as e:
        duration = time.time() - start_time
        res = {"status": "error", "error": str(e)}
        log_tool_receipt(name, args, res, model=model_name, status="failed", duration_sec=duration)
        return res

def get_tools_for_model(model_name: str) -> List[Dict[str, Any]]:
    """Filter tools based on model capability (hardware tiering)."""
    # Simple tiering based on model name
    # e.g., only provide CU tools to models that are larger/more capable
    # For now, return all tools, but can be customized based on model
    
    # Example logic: smaller models don't get computer use tools
    if "1.5b" in model_name.lower():
        return AGENT_DEFS
    
    return ALL_DEFINITIONS
