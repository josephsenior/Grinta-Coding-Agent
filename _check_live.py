import requests, json

r = requests.get('http://localhost:3000/api/v1/conversations', timeout=5)
convs = r.json()['results']
# Find the running one
for c in convs:
    if c['status'] == 'running':
        cid = c['conversation_id']
        break
else:
    print('No running conversation')
    exit()

print(f'CID: {cid[:12]}')

# Get state
r2 = requests.get(f'http://localhost:3000/api/v1/conversations/{cid}', timeout=10)
d = r2.json()
print(f'State: {d.get("agent_state")}')

# Get events
r3 = requests.get(f'http://localhost:3000/api/v1/conversations/{cid}/events?start_id=0', timeout=10)
events = r3.json().get('events', [])
print(f'Events: {len(events)}')

# Count files
files = set()
errors = 0
stuck = 0
for e in events:
    content = str(e.get('content', ''))
    obs = e.get('observation', '')
    if 'File written:' in content:
        for part in content.split('File written: ')[1:]:
            p = part.split(' (')[0].strip()
            if p:
                files.add(p.replace('/workspace/', '').lstrip('/'))
    if obs == 'error':
        errors += 1
        if 'STUCK' in content or 'stuck' in content.lower():
            stuck += 1

print(f'Files: {len(files)}, Errors: {errors}, Stuck: {stuck}')

# Last 3 events
print('\nLast 3:')
for e in events[-3:]:
    eid = e.get('id', '?')
    act = e.get('action', '')
    obs = e.get('observation', '')
    content = str(e.get('content', ''))[:120]
    print(f'  E{eid}: act={act} obs={obs} | {content}')
