import os
import subprocess
import json
import urllib.request
import urllib.parse
import webbrowser
import tempfile
import shutil
from typing import Dict, Any, List

def run_powershell(script: str) -> str:
    try:
        # Pass script as base64 or just raw string via -Command
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return f"Error: {result.stderr.strip()}"
        return result.stdout.strip()
    except Exception as e:
        return f"Exception: {str(e)}"

def screenshot_tool() -> Dict[str, Any]:
    try:
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, "screenshot.png")
        ps_script = f"""
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bmp = New-Object System.Drawing.Bitmap $bounds.width, $bounds.height
        $graphics = [System.Drawing.Graphics]::FromImage($bmp)
        $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.size)
        $bmp.Save('{file_path}')
        $graphics.Dispose()
        $bmp.Dispose()
        """
        res = run_powershell(ps_script)
        if "Error:" in res or "Exception:" in res:
            return {"status": "error", "message": res}
        return {"status": "success", "file": file_path}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def browser_navigate(url: str) -> Dict[str, Any]:
    try:
        webbrowser.open(url)
        return {"status": "success", "url": url}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def browser_search(query: str) -> Dict[str, Any]:
    try:
        # Search Google
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.google.com/search?q={encoded_query}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            # Extract basic text or return a summary (simplistic for stdlib)
            content = html[:1000] # return first 1000 chars as placeholder
            return {"status": "success", "url": url, "content_snippet": content}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def file_manager(action: str, path: str, dest: str = None, content: str = None) -> Dict[str, Any]:
    try:
        if action == "list":
            if not os.path.exists(path):
                return {"status": "error", "message": f"Path not found: {path}"}
            items = os.listdir(path)
            return {"status": "success", "items": items}
        elif action == "read":
            with open(path, "r", encoding="utf-8") as f:
                return {"status": "success", "content": f.read()}
        elif action == "write":
            if content is None:
                return {"status": "error", "message": "Content required for write"}
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"status": "success"}
        elif action == "copy":
            if dest is None:
                return {"status": "error", "message": "Dest required for copy"}
            shutil.copy(path, dest)
            return {"status": "success"}
        elif action == "move":
            if dest is None:
                return {"status": "error", "message": "Dest required for move"}
            shutil.move(path, dest)
            return {"status": "success"}
        elif action == "delete":
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return {"status": "success"}
        else:
            return {"status": "error", "message": "Unknown action"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def run_command(cmd: str) -> Dict[str, Any]:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return {
            "status": "success" if result.returncode == 0 else "error",
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def clipboard_read() -> Dict[str, Any]:
    try:
        res = run_powershell("Get-Clipboard")
        if "Error:" in res or "Exception:" in res:
            return {"status": "error", "message": res}
        return {"status": "success", "content": res}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def clipboard_write(text: str) -> Dict[str, Any]:
    try:
        # escape quotes
        safe_text = text.replace("'", "''")
        res = run_powershell(f"Set-Clipboard -Value '{safe_text}'")
        if "Error:" in res or "Exception:" in res:
            return {"status": "error", "message": res}
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def window_list() -> Dict[str, Any]:
    try:
        ps_script = 'Get-Process | Where-Object { $_.MainWindowTitle } | Select-Object Name, MainWindowTitle | ConvertTo-Json'
        res = run_powershell(ps_script)
        if "Error:" in res or "Exception:" in res:
            return {"status": "error", "message": res}
        data = json.loads(res) if res.strip() else []
        return {"status": "success", "windows": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def mouse_click(x: int, y: int) -> Dict[str, Any]:
    try:
        ps_script = f"""
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point({x}, {y})
        # Note: True clicking requires user32.dll mouse_event.
        $signature = @'
        [DllImport("user32.dll",CharSet=CharSet.Auto, CallingConvention=CallingConvention.StdCall)]
        public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint cButtons, uint dwExtraInfo);
'@
        $mouse = Add-Type -memberDefinition $signature -name "MouseClick" -namespace "Win32" -PassThru
        $mouse::mouse_event(0x0002, 0, 0, 0, 0) # Left down
        $mouse::mouse_event(0x0004, 0, 0, 0, 0) # Left up
        """
        res = run_powershell(ps_script)
        if "Error:" in res or "Exception:" in res:
            return {"status": "error", "message": res}
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def keyboard_type(text: str) -> Dict[str, Any]:
    try:
        safe_text = text.replace("'", "''")
        ps_script = f"""
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.SendKeys]::SendWait('{safe_text}')
        """
        res = run_powershell(ps_script)
        if "Error:" in res or "Exception:" in res:
            return {"status": "error", "message": res}
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Schemas
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "screenshot_tool",
            "description": "Takes a screenshot and saves it to a temporary file.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Opens a URL in the default web browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to navigate to."}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": "Searches Google for the given query and returns a snippet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_manager",
            "description": "Perform file operations (list, read, write, copy, move, delete).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "read", "write", "copy", "move", "delete"]},
                    "path": {"type": "string", "description": "Target file or directory path."},
                    "dest": {"type": "string", "description": "Destination path for copy or move."},
                    "content": {"type": "string", "description": "Content to write to the file."}
                },
                "required": ["action", "path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "The command to run."}
                },
                "required": ["cmd"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_read",
            "description": "Reads text from the clipboard.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clipboard_write",
            "description": "Writes text to the clipboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to write."}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "window_list",
            "description": "Lists all open windows with titles.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_click",
            "description": "Clicks the mouse at the given coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate."},
                    "y": {"type": "integer", "description": "Y coordinate."}
                },
                "required": ["x", "y"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "keyboard_type",
            "description": "Types the given text using the keyboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to type."}
                },
                "required": ["text"]
            }
        }
    }
]

TOOL_DISPATCH = {
    "screenshot_tool": screenshot_tool,
    "browser_navigate": lambda **kw: browser_navigate(kw.get("url")),
    "browser_search": lambda **kw: browser_search(kw.get("query")),
    "file_manager": lambda **kw: file_manager(kw.get("action"), kw.get("path"), kw.get("dest"), kw.get("content")),
    "run_command": lambda **kw: run_command(kw.get("cmd")),
    "clipboard_read": clipboard_read,
    "clipboard_write": lambda **kw: clipboard_write(kw.get("text")),
    "window_list": window_list,
    "mouse_click": lambda **kw: mouse_click(kw.get("x"), kw.get("y")),
    "keyboard_type": lambda **kw: keyboard_type(kw.get("text"))
}
