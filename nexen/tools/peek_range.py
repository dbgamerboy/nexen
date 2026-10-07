import sys
sys.path.insert(0, r"H:\NEXEN-ENTERPRISE\Apps\NEXEN\engine")
from nexen.connectors import base  # noqa: E402

a, b, width = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
rows = base.ro_query(r"%USERPROFILE%\AppData\Local\hermes\state.db",
                     "select id,role,tool_name,content from messages where id between ? and ? order by id", (a, b))
for r in rows:
    print(r["id"], r["role"], r["tool_name"] or "", "::", base.redact((r["content"] or "")[:width]).replace("\n", " "))
    print("--")
