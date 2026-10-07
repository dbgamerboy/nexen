"""One-time wiring: registry buttons, server routes and UI handler now use engine/nexen/actions.py."""
from pathlib import Path

APP = Path(__file__).resolve().parents[1]

p = APP / "engine/nexen/registry.py"
s = p.read_text(encoding="utf-8")
if "from . import actions" not in s:
    old = s[s.index("def marvin_buttons():"):s.index("def f_census")]
    new = '''def marvin_buttons():
    """Action buttons from the app's own catalog (config/actions.json). Executed by actions.py."""
    from . import actions
    return [{"id": "action-" + a["id"], "label": a["label"], "kind": "marvin-action", "target": a["id"], "risk": a.get("risk", "confirm"),
             "lane": a.get("lane"), "help": a.get("help", ""), "inputs": actions.public(a)["inputs"],
             "group": "Actions: " + str(a.get("lane", "other"))} for a in actions.catalog()]


'''
    s = s.replace(old, new)
    s = s.replace('TRUSTED_ROOTS = [Path(r"H:\\NEXEN-ENTERPRISE")', 'TRUSTED_ROOTS = [Path(r"F:\\NEXEN_MEMORY"), Path(r"H:\\NEXEN-ENTERPRISE")')
    p.write_text(s, encoding="utf-8")

p = APP / "engine/nexen/server.py"
s = p.read_text(encoding="utf-8")
if "actions.request" not in s:
    i = s.index('        if path == "/api/marvin-action":')
    j = s.index('        m = re.fullmatch(r"/api/approvals/')
    s = s[:i] + '''        if path == "/api/marvin-action":
            from . import actions
            return actions.request(b.get("id", ""), b.get("inputs") or {}, source="ui", confirmed=bool(b.get("confirmed")))
''' + s[j:]
    s = s.replace('        if path == "/api/buttons":', '        if path == "/api/action-runs":\n            from . import actions\n            return actions.recent()\n        if path == "/api/buttons":', 1)
    p.write_text(s, encoding="utf-8")

p = APP / "ui/index.html"
s = p.read_text(encoding="utf-8")
old = "else if(b.kind==='marvin-action')show('bizview')(await post('/api/marvin-action',{id:b.target}));"
if old in s:
    s = s.replace(old, "else if(b.kind==='marvin-action')await runAction(b);")
    s = s.replace("async function loadConn(){", '''async function runAction(b){const inputs={};for(const i of (b.inputs||[])){if(i.secret){show('bizview')('This field is a secret. Set it in Windows user environment settings; this app never handles it.');return}
 const v=prompt(i.label||i.name);if(v===null)return;inputs[i.name]=v}
 let r=await post('/api/marvin-action',{id:b.target,inputs});
 if(r.status==='needs_confirm'){if(!confirm((r.label||b.label)+'\\n\\n'+(r.help||'Run this?')))return;r=await post('/api/marvin-action',{id:b.target,inputs,confirmed:true})}
 show('bizview')(r.content?((r.record&&r.record.summary)||'')+'\\n\\n'+r.content:r)}
async function loadConn(){''', 1)
    s = s.replace("Buttons open or read the existing programs.", "Every button runs inside this app.")
    p.write_text(s, encoding="utf-8")
print("wired")
