import sqlite3, json

def parse_row(d):
    out = dict(d)
    for k, v in list(out.items()):
        if isinstance(v, str) and v[:1] in '{[':
            try:
                out[k] = json.loads(v)
            except Exception:
                pass
    return out

db = r"c:\Users\GIGABYTE\.grinta\workspaces\a6dee3cbdba069e15cc10a2844236109\storage\sessions\40f19f49-7745-4d-0f7464b1e1341f5\events\events.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()
res = {}
res['schema'] = {}
for name, sql in cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"):
    res['schema'][name] = {
        'sql': sql,
        'columns': [r['name']+':'+r['type'] for r in cur.execute(f"PRAGMA table_info({name})")]
    }
row413 = cur.execute("SELECT * FROM events WHERE id=413").fetchone()
res['event_413'] = parse_row(dict(row413)) if row413 else None
rows = [parse_row(dict(r)) for r in cur.execute("SELECT * FROM events WHERE id BETWEEN 408 AND 418 ORDER BY id")]
rels = []
for d in rows:
    s = json.dumps(d, ensure_ascii=False)
    if d.get('id') == 413 or 'DebuggerAction' in s or 'observation' in s.lower() or 'error' in s.lower():
        rels.append(d)
res['relevant'] = rels
print(json.dumps(res, ensure_ascii=False, indent=2))
con.close()
