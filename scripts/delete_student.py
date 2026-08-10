import os, sys, json
# Ensure project root on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database import get_db, _fix

if len(sys.argv) < 2:
    print(json.dumps({'error': 'Usage: delete_student.py <user_id>'}))
    sys.exit(1)

uid = sys.argv[1]
conn = get_db()
cur = conn.cursor()
cur.execute(_fix('DELETE FROM users WHERE id = %s'), (uid,))
# rowcount may be -1 for some DB drivers; fetch count via a select as fallback
try:
    deleted = cur.rowcount
except Exception:
    deleted = None
conn.commit()
if deleted is None or deleted < 0:
    # try to confirm
    cur2 = conn.cursor()
    cur2.execute(_fix('SELECT COUNT(1) as c FROM users WHERE id = %s'), (uid,))
    remaining = cur2.fetchone()[0]
    deleted = 0 if remaining else 1
conn.close()
print(json.dumps({'deleted': deleted, 'uid': uid}))
