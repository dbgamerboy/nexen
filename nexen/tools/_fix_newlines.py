from pathlib import Path
root = Path(r"H:\NEXEN-ENTERPRISE\Apps\NEXEN\engine\nexen")
fixes = {
    "brain.py": [('name="marvin"):\\n        name = identity.agent_key(name)\\n        if name', 'name="marvin"):\n        name = identity.agent_key(name)\n        if name')],
    "mcp_server.py": [('swarm; "jarvis" is accepted as an alias of marvin)', 'swarm; jarvis is accepted as an alias of marvin)')],
}
for rel, pairs in fixes.items():
    p = root / rel
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        s = s.replace(a, b)
    compile(s, str(p), "exec")
    p.write_text(s, encoding="utf-8", newline="")
    print("fixed", rel)
