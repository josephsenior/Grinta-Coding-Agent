import requests, json
try:
    r = requests.get('http://localhost:3000/api/v1/conversations', timeout=5)
    print('Server UP')
    convs = r.json()['results']
    print(f'{len(convs)} conversations')
    for c in convs[:5]:
        cid = c['conversation_id'][:12]
        status = c['status']
        print(f'  {cid} | {status}')
except Exception as e:
    print(f'Server error: {e}')
