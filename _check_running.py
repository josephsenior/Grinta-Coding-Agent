import requests, json

cid = '8045ae7b14d5'
# Get full CID
r = requests.get('http://localhost:3000/api/v1/conversations', timeout=5)
convs = r.json()['results']
full_cid = None
for c in convs:
    if c['conversation_id'].startswith(cid):
        full_cid = c['conversation_id']
        break

print(f'Full CID: {full_cid}')

# Get conversation details
r2 = requests.get(f'http://localhost:3000/api/v1/conversations/{full_cid}', timeout=10)
details = r2.json()
print(f'State: {details.get("agent_state")}')
print(f'Status: {details.get("status")}')

# Count events
r3 = requests.get(f'http://localhost:3000/api/v1/conversations/{full_cid}/events?start_id=0', timeout=10)
events = r3.json().get('events', [])
print(f'Events: {len(events)}')

# Count files 
files = set()
for e in events:
    content = str(e.get('content', ''))
    if 'File written:' in content:
        parts = content.split('File written: ')
        for part in parts[1:]:
            p = part.split(' (')[0].strip()
            if p:
                files.add(p.replace('/workspace/', '').lstrip('/'))

print(f'Unique files: {len(files)}')
if files:
    print(f'Files: {sorted(files)}')

# Last few events
print(f'\nLast 5 events:')
for e in events[-5:]:
    eid = e.get('id', '?')
    action = e.get('action', '')
    obs = e.get('observation', '')
    content = str(e.get('content', ''))[:100]
    print(f'  E{eid}: act={action} obs={obs} | {content}')
