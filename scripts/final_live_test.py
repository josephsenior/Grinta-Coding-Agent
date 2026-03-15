
import urllib.request, json, time, sys;

base='http://127.0.0.1:3000'

req = urllib.request.Request(f'{base}/api/v1/conversations', headers={'Content-Type':'application/json'}, data=b'{}')
cid = json.loads(urllib.request.urlopen(req).read())['conversation_id']
print(f'Started Conversation: {cid}')

prompt = 'Create a new folder named my_flask_app_test. Inside it, write pp.py with a simple Flask Hello World server. Make sure you use your file write tool!'

req2 = urllib.request.Request(f'{base}/api/v1/conversations/{cid}/events/raw', headers={'Content-Type':'text/plain'}, data=prompt.encode('utf-8'))
urllib.request.urlopen(req2)
print('Task dispatched. Waiting for agent...')

for _ in range(60):
    time.sleep(2)
    st = json.loads(urllib.request.urlopen(f'{base}/api/v1/conversations/{cid}').read())['agent_state']
    print(f'State: {st}')
    if st in ['awaiting_user_input', 'finished', 'stopped']:
        break

print('Done!')
