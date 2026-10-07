import sqlite3
import sys

con = sqlite3.connect("file:H:/NEXEN-ENTERPRISE/Data/V4/learning.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = con.execute("SELECT id,text,supersedes,meta FROM items WHERE supersedes IS NOT NULL").fetchall()
for r in rows:
    old = con.execute("SELECT text FROM items WHERE id=?", (r["supersedes"],)).fetchone()
    print("NEW:", r["text"][:230].replace("\n", " "))
    print("OLD:", (old["text"] if old else "?")[:230].replace("\n", " "))
    print("META:", r["meta"][:120])
    print("-----")
