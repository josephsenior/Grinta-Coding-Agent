import sqlite3, json
from collections.abc import Mapping, Sequence

db = r"c:\Users\GIGABYTE\.grinta\workspaces\a6dee3cbdba069e15cc10a2844236109\storage\sessions\40f19f49-7745-4d-0f7464b1e1341f5\events\events.db"
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
cur = con.cursor()

def parse(v):
    if isinstance(v, str) and v[:1] in '{[':
        try:
            return json.loads(v)
        except Exception:
            return v
    return v

def parse_row(row):
    d = dict(row)
    return {k: parse(v) for k,v in d.items()}

def walk(obj, path='$'):
    yield path, obj
    if isinstance(obj, Mapping):
        for k,v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i,v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")

def interesting(obj):
    if isinstance(obj, Mapping):
        text = json.dumps(obj, ensure_ascii=False)
        low = text.lower()
        if 'debuggeraction' in text or 'observation' in low or 'error' in low:
            return True
    return False

schema_sql = cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='events'").fetchone()[0]
cols = [dict(r) for r in cur.execute("PRAGMA table_info(events)")]
print('EVENTS_SCHEMA_SQL')
print(schema_sql)
print('EVENTS_COLUMNS')
print(json.dumps(cols, ensure_ascii=False, indent=2))

row413 = parse_row(cur.execute("SELECT * FROM events WHERE id=413").fetchone())
print('ROW_413_COLUMN_SUMMARY')
summary = {}
for k,v in row413.items():
    if isinstance(v, str):
        summary[k] = {'type':'str','len':len(v),'preview':v[:200]}
    else:
        summary[k] = {'type':type(v).__name__}
print(json.dumps(summary, ensure_ascii=False, indent=2))
print('ROW_413_MATCHES')
for p,o in walk(row413):
    if interesting(o):
        print(p)
        print(json.dumps(o, ensure_ascii=False, indent=2))

print('NEARBY_MATCHES')
for row in cur.execute("SELECT * FROM events WHERE id BETWEEN 408 AND 418 ORDER BY id"):
    d = parse_row(row)
    found = []
    for p,o in walk(d):
        if interesting(o):
            found.append((p,o))
    if found:
        print(f"EVENT {d.get('id')}")
        for p,o in found[:10]:
            print(p)
            print(json.dumps(o, ensure_ascii=False, indent=2))
con.close()
