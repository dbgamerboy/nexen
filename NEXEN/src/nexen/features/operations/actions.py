"""The one executor behind every action button, CLI call and API call.

The catalog lives in config/actions.json. Kinds: process (runs, logged, timeout), launch (starts and leaves running),
view (shows a file, folder or local page), edit (opens the file in the default editor), gallery (lists clips),
internal (a handler below), system (hands a script to Windows, which shows its own admin prompt).
Inputs never go through a shell and cannot start with '-'. risk=confirm needs the owner's click (confirmed=True).
Nothing in the catalog posts, sends, spends or signs in; the secret form (Discord token) is deliberately not handled here.
"""
import csv
import ctypes
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from nexen.core import paths

CATALOG = paths.APP / "config" / "actions.json"
RUNS = []
_lock = threading.Lock()
MAX_VIEW = 40000


def vars_():
    v = paths.vault()
    return {"python": r"H:\NEXEN\marvin\tts\venv\Scripts\python.exe", "nexen": str(paths.H_NEXEN), "vault": str(v) if v else r"F:\NEXEN_MEMORY",
            "bus": str(paths.H_NEXEN / "marvin" / "bus"), "whop": str(paths.H_NEXEN / "whop")}


def _expand(s, v, inputs=None):
    s = re.sub(r"\$\{(\w+)\}", lambda m: v.get(m.group(1), m.group(0)), str(s))
    return re.sub(r"\{(\w+)\}", lambda m: (inputs or {}).get(m.group(1), m.group(0)), s)


def catalog():
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8-sig")).get("actions", [])
    except (OSError, ValueError):
        return []


def public(a):
    return {k: a.get(k) for k in ("id", "label", "lane", "risk", "kind", "help")} | {"inputs": [{k: i.get(k) for k in ("name", "label", "type", "required", "secret", "pattern")} for i in a.get("inputs", [])]}


def validate(action, inputs):
    out = {}
    for d in action.get("inputs", []):
        val = str((inputs or {}).get(d["name"], "") or "").strip()
        if not val:
            if d.get("required"):
                raise ValueError("%s is required" % d.get("label", d["name"]))
            out[d["name"]] = ""
            continue
        if len(val) > 1000 or re.search(r"[\r\n\0]", val):
            raise ValueError("%s: too long or has line breaks" % d["name"])
        if val.startswith("-"):
            raise ValueError("%s: cannot start with '-'" % d["name"])
        if d.get("type") == "number" and not re.fullmatch(r"-?\d+(\.\d+)?", val):
            raise ValueError("%s: must be a number" % d["name"])
        if d.get("pattern") and not re.search(d["pattern"], val):
            raise ValueError("%s: does not match %s" % (d["name"], d["pattern"]))
        out[d["name"]] = val
    return out


def _ps(script, timeout=30):
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], capture_output=True, text=True, timeout=timeout, creationflags=0x08000000)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _ollama(path, body=None, timeout=4):
    req = urllib.request.Request(paths.OLLAMA_URL + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------------------------------------------------------- internal handlers
def h_logResult(i):
    f = paths.H_NEXEN / "marvin" / "results.csv"
    new = not f.exists()
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "lane", "item", "views", "dollars", "hours"])
        w.writerow([time.strftime("%Y-%m-%d"), i["lane"], i["item"], i.get("views") or 0, i["dollars"], i["hours"]])
    return "Logged $%s for %s (%s h). Lanes re-rank by $/hour." % (i["dollars"], i["lane"], i["hours"])


def h_loopPause(i=None):
    paths.STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    paths.STOP_FILE.write_text("paused from NEXEN %s\n" % time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
    return "The loop stops before its next job."


def h_loopResume(i=None):
    if not paths.STOP_FILE.exists():
        return "The loop was not paused."
    paths.STOP_FILE.unlink()
    return "Loop resumed. It picks up the next queued job."


def h_gamingMode(i=None):
    try:
        names = [m["name"] for m in _ollama("/api/ps").get("models", [])]
    except Exception:
        names = None
    if names is None:
        msg = "Ollama is not running, so the GPU holds no models."
    else:
        for n in names:
            try:
                _ollama("/api/generate", {"model": n, "keep_alive": 0}, timeout=15)
            except Exception:
                pass
        msg = ("Unloaded %s from VRAM." % ", ".join(names)) if names else "No models were loaded."
    return msg + " " + h_loopPause() + ' Use "Resume the 24/7 loop" after gaming.'


def h_ollamaStart(i=None):
    for _ in range(2):  # a loaded machine answers slowly: 8 s per probe, twice, before declaring it down (problem ENV-003)
        try:
            _ollama("/api/version", timeout=8)
            return "Ollama is already running."
        except Exception:
            pass
    if subprocess.run(["tasklist", "/FI", "IMAGENAME eq ollama.exe"], capture_output=True, text=True, creationflags=0x08000000).stdout.lower().count("ollama.exe"):
        return "Ollama is running but busy; it did not answer in 16 s. Not starting a second copy."
    exe = next((p for p in (r"H:\NEXEN\ollama-runtime\ollama.exe", os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")) if Path(p).exists()), None)
    if not exe:
        raise RuntimeError("Ollama executable not found")
    subprocess.Popen([exe, "serve"], creationflags=0x08000008, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env={**os.environ, "OLLAMA_MODELS": r"H:\NEXEN\models\ollama", "OLLAMA_KEEP_ALIVE": "2h"})
    return "Starting Ollama."


_BOT = "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'marvin_discord_voice' }"
_LOOP = "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { $_.CommandLine -match 'marvin-autostart' }"


def _start_autostart():
    script = paths.H_NEXEN / "marvin" / "marvin-autostart.ps1"
    if not script.exists():
        raise RuntimeError("MARVIN autostart script is missing: %s" % script)
    subprocess.Popen(["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-File", str(script)], creationflags=0x08000008,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def h_marvinStart(i=None):
    rc, out, _ = _ps("(%s | Measure-Object).Count" % _BOT)
    if out.isdigit() and int(out) > 0:
        return "MARVIN is already running."
    _start_autostart()
    return "Starting MARVIN. He is online in about 20 seconds."


def h_marvinRestart(i=None):
    _, loop, _ = _ps("(%s | Measure-Object).Count" % _LOOP)
    _ps("%s | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % _BOT)
    if loop.isdigit() and int(loop) > 0:
        return "Stopped MARVIN. His autostart loop brings him back in about 15 seconds."
    _start_autostart()
    return "Stopped MARVIN and started his autostart loop."


def h_discordSetup(i):
    raise RuntimeError("The Discord token is a secret. Enter it in Windows user environment settings; this app never stores or handles it.")


def _exe_for_autostart():
    exe = paths.APP / "NEXEN.exe"
    return exe if exe.exists() else None


def h_autostartOn(i=None):
    exe = _exe_for_autostart()
    if not exe:
        raise RuntimeError("NEXEN exe not found")
    _ps("Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name 'NEXEN' -Value '\"%s\"'" % exe)
    return "NEXEN now starts with Windows."


def h_autostartOff(i=None):
    _ps("Remove-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name 'NEXEN' -ErrorAction SilentlyContinue")
    return "NEXEN no longer starts with Windows."


def h_catalogRefresh(i=None):
    from nexen.core import registry
    mods = registry.all_modules(with_probe=True)
    tools = sum(1 for _ in (paths.H_NEXEN / "tools").glob("*")) if (paths.H_NEXEN / "tools").is_dir() else 0
    skills = sum(1 for _ in (paths.KNOWLEDGE / "skills").glob("*")) if (paths.KNOWLEDGE / "skills").is_dir() else 0
    return "Rescanned: %d modules (%d up), %d tools, %d skills." % (len(mods), sum(1 for m in mods if m["health"]["state"] in ("up", "present")), tools, skills)


def h_awayResearch(i=None):
    if (paths.H_NEXEN / "marvin" / "bus" / "MONEY-STOP").exists() or (paths.H_NEXEN / "marvin" / "STOP").exists():
        return "Research remains stopped by its persistent STOP."
    k = ctypes.windll.kernel32
    k.OpenEventW.restype = ctypes.c_void_p
    h = k.OpenEventW(0x0002, False, "Local\\NEXEN_MONEY_WAKE")
    if not h:
        raise RuntimeError("Research worker is unavailable or busy; no extra worker was launched.")
    k.SetEvent(ctypes.c_void_p(h))
    k.CloseHandle(ctypes.c_void_p(h))
    return "Existing research worker signaled; its heartbeat is the completion evidence."


def h_contentDaily(i=None):
    r = subprocess.run([str(paths.PYTHON), "-B", r"H:\NEXEN\publishing\daily.py"], capture_output=True, text=True, timeout=370, creationflags=0x08000000,
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        raise RuntimeError("Daily content worker failed or hit its deadline; inspect its receipt.")
    return (r.stdout or "").strip()[-500:]


HANDLERS = {n[2:]: f for n, f in list(globals().items()) if n.startswith("h_")}


# ---------------------------------------------------------------- views
def _view(kind, target):
    if target.lower().startswith(("http://127.0.0.1", "http://localhost")):
        os.startfile(target)
        return {"summary": "opened %s in your browser" % target}
    p = Path(target)
    if p.is_dir():
        files = sorted(p.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:40]
        if kind == "gallery":
            files = [f for f in sorted(p.rglob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)[:40]]
        os.startfile(str(p))
        return {"summary": "opened folder %s" % p, "entries": [f.name for f in files]}
    if p.is_file():
        if kind == "edit":
            os.startfile(str(p))
            return {"summary": "opened %s in your editor" % p.name}
        raw = p.read_bytes()
        text = raw[-MAX_VIEW:].decode("utf-8", errors="replace")
        return {"summary": "%s (%d bytes%s)" % (p.name, len(raw), ", last %d shown" % MAX_VIEW if len(raw) > MAX_VIEW else ""), "content": text}
    return {"error": "not found: %s" % target}


# ---------------------------------------------------------------- executor
def _record(action, source):
    rec = {"run": "%x" % int(time.time() * 1000), "action": action["id"], "label": action["label"], "source": source, "status": "running",
           "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "ended": None, "summary": "", "log": None}
    with _lock:
        RUNS.append(rec)
        del RUNS[:-200]
    return rec


def _finish(rec, status, summary):
    rec.update(status=status, summary=str(summary)[-600:], ended=time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        log = paths.DATA / "action-runs.jsonl"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass
    return rec


def _spawn(action, inputs, rec):
    v = vars_()
    exe = _expand(action["exe"], v)
    args = [_expand(a, v, inputs) for a in action.get("args", [])]
    cwd = _expand(action["cwd"], v) if action.get("cwd") else None
    logdir = paths.DATA / "action-logs"
    logdir.mkdir(parents=True, exist_ok=True)
    rec["log"] = str(logdir / ("%s-%s.log" % (time.strftime("%Y%m%d-%H%M%S"), action["id"])))
    if action["kind"] == "launch":
        subprocess.Popen([exe] + args, cwd=cwd, creationflags=0x00000008 | 0x00000200, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _finish(rec, "done", "launched")
        return

    def run():
        with open(rec["log"], "w", encoding="utf-8") as lf:
            lf.write("# %s %s\n" % (exe, json.dumps(args)))
            try:
                p = subprocess.Popen([exe] + args, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=0x08000000,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                p.wait(timeout=action.get("timeoutMin", 30) * 60)
                tail = Path(rec["log"]).read_text(encoding="utf-8", errors="replace").strip().splitlines()[-3:]
                _finish(rec, "done" if p.returncode == 0 else "failed", "exit %s: %s" % (p.returncode, " | ".join(tail)))
            except subprocess.TimeoutExpired:
                p.kill()
                _finish(rec, "failed", "stopped after %s minutes" % action.get("timeoutMin", 30))
            except Exception as exc:
                _finish(rec, "failed", "%s: %s" % (type(exc).__name__, exc))
    threading.Thread(target=run, daemon=True).start()


def request(action_id, inputs=None, source="ui", confirmed=False):
    action = next((a for a in catalog() if a["id"] == action_id), None)
    if not action:
        return {"status": "error", "error": "no action '%s'" % action_id}
    try:
        clean = validate(action, inputs or {})
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}
    if action.get("risk") == "confirm" and not (source == "ui" and confirmed):
        return {"status": "needs_confirm", "label": action["label"], "help": action.get("help", "")}
    rec = _record(action, source)
    v = vars_()
    try:
        k = action["kind"]
        if k in ("view", "edit", "gallery"):
            res = _view(k, _expand(action["target"], v))
            _finish(rec, "failed" if res.get("error") else "done", res.get("summary") or res.get("error"))
            return {"status": rec["status"], "record": rec, **{x: res[x] for x in ("content", "entries", "error") if x in res}}
        if k == "system":
            _ps("Start-Process -FilePath '%s' -Verb RunAs" % _expand(action["target"], v), timeout=20)
            _finish(rec, "done", "handed to Windows (admin prompt)")
        elif k == "internal":
            fn = HANDLERS.get(action["handler"])
            if not fn:
                raise RuntimeError("handler %s missing" % action["handler"])
            _finish(rec, "done", fn(clean) if action.get("inputs") else fn())
        else:
            _spawn(action, clean, rec)
            return {"status": "started", "record": rec}
        return {"status": "done", "record": rec}
    except Exception as exc:
        _finish(rec, "failed", "%s: %s" % (type(exc).__name__, exc))
        return {"status": "error", "error": str(exc), "record": rec}


def recent(n=30):
    with _lock:
        return list(reversed(RUNS))[:n]
