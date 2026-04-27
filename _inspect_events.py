import sqlite3, json

db = r"c:\Users\GIGABYTE\.grinta\workspaces\a6dee3cbdba069e15cc10a2844236109\storage\sessions\40f19f49-7745-4d-0f7464b1e1341f5\events\events.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
res = {}
res['tables'] = []
for name, sql in cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"):
    cols = [dict(r) for r in cur.execute(f"PRAGMA table_info({name})")]
    res['tables'].append({'name': name, 'sql': sql, 'columns': cols})
res['event_413'] = dict(cur.execute("SELECT * FROM events WHERE id=413").fetchone())
rows = [dict(r) for r in cur.execute("SELECT * FROM events WHERE id BETWEEN 408 AND 418 ORDER BY id")]
res['nearby'] = rows
res['relevant'] = []
for d in rows:
    parsed = {}
    for k, v in d.items():
        if isinstance(v, str) and v[:1] in '{[':
            try:
                parsed[k] = json.loads(v)
            except Exception:
                pass
    blob = json.dumps({**d, **parsed}, ensure_ascii=False)
    if d['id'] == 413 or 'DebuggerAction' in blob or 'observation' in blob.lower() or 'error' in blob.lower():
        x = d.copy(); x.update({f'parsed_{k}': v for k, v in parsed.items()}); res['relevant'].append(x)
print(json.dumps(res, ensure_ascii=False, indent=2))
con.close()
