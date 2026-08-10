import json
import os, sys
# Ensure project root is on sys.path so `import database` works when running from scripts/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database import get_db, _fix

conn = get_db()
cur = conn.cursor()
cur.execute(_fix("SELECT id,email,name,department,semester,section,role FROM users WHERE department=%s AND semester=%s AND section=%s AND role=%s"), ("Computer Science","6","6B","student"))
rows = cur.fetchall()
out = []
for r in rows:
    try:
        d = dict(r)
    except Exception:
        d = {desc[0]: r[i] for i, desc in enumerate(cur.description)}
    out.append(d)
print(json.dumps(out, indent=2))
conn.close()
