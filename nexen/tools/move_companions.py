"""Moves the three Claude companion tools into NEXEN\\companion and rewrites every path that pointed at the old homes.
Nothing is deleted. Old folders are moved, not copied. A report is written next to this file."""
import json, os, re, shutil, sys

V4 = r"H:\NEXEN-ENTERPRISE\Apps\NEXEN"
DEST = os.path.join(V4, "companion")
MOVES = {r"H:\NEXEN\marvin-training": os.path.join(DEST, "marvin-training"),
         r"H:\NEXEN\desktop-organizer": os.path.join(DEST, "desktop-organizer"),
         r"H:\NEXEN\nexen-next": os.path.join(DEST, "nexen-next")}
TEXT = (".py", ".cmd", ".md", ".html", ".json", ".txt", ".ps1")
report = {"moved": [], "rewritten": [], "skipped": []}

os.makedirs(DEST, exist_ok=True)
for old, new in MOVES.items():
    if os.path.exists(new): report["skipped"].append(f"{new} exists"); continue
    if not os.path.isdir(old): report["skipped"].append(f"{old} missing"); continue
    shutil.move(old, new); report["moved"].append([old, new])

pairs = []
for old, new in MOVES.items():
    pairs += [(old, new), (old.replace("\\", "\\\\"), new.replace("\\", "\\\\")), (old.replace("\\", "/"), new.replace("\\", "/"))]

for old, new in MOVES.items():
    for root, dirs, files in os.walk(new):
        dirs[:] = [d for d in dirs if d not in ("manifests", "results", "_work", "export", "__pycache__")]
        for fn in files:
            if not fn.lower().endswith(TEXT) or fn == "move_companions.py": continue
            p = os.path.join(root, fn)
            try: t = open(p, encoding="utf-8").read()
            except (UnicodeDecodeError, OSError): continue
            t2 = t
            for a, b in pairs: t2 = t2.replace(a, b)
            if t2 != t:
                open(p, "w", encoding="utf-8", newline="").write(t2); report["rewritten"].append(p)

# V4 module list
mp = os.path.join(V4, "modules", "companion-tools.json")
t = open(mp, encoding="utf-8").read(); t2 = t
for a, b in pairs: t2 = t2.replace(a, b)
if t2 != t: open(mp, "w", encoding="utf-8", newline="").write(t2); report["rewritten"].append(mp)
json.loads(t2)

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "move_companions.report.json"), "w") as f: json.dump(report, f, indent=1)
print(json.dumps({k: len(v) for k, v in report.items()}), report["skipped"])
