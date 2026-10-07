import re
import sys
sys.path.insert(0, r"H:\NEXEN-ENTERPRISE\Apps\NEXEN\engine")
from nexen.connectors import base  # noqa: E402

sid, term = sys.argv[1], sys.argv[2]
rows = base.ro_query(r"%USERPROFILE%\AppData\Local\hermes\state.db",
                     "select id,role,content from messages where session_id=? and content like ? order by id", (sid, "%" + term + "%"))
seen = set()
for r in rows[:8]:
    t = r["content"] or ""
    m = re.search("(?i)" + re.escape(term), t)
    a = max(0, m.start() - 600)
    chunk = base.redact(t[a:m.start() + 1100]).replace("\n", " ")
    if chunk[:80] in seen:
        continue
    seen.add(chunk[:80])
    print(r["role"], r["id"], "::", chunk)
    print("-----")
