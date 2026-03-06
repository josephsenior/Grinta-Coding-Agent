import urllib.request
import json
import uuid
import time
import sys

conv_id = uuid.uuid4().hex

def post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req).read().decode())

def get(url):
    return json.loads(urllib.request.urlopen(url).read().decode())

print("Creating conversation...")
post("http://127.0.0.1:3000/api/v1/conversations", {"conversation_id": conv_id})

print("Sending 'hi' to /events/raw...")
post(f"http://127.0.0.1:3000/api/v1/conversations/{conv_id}/events/raw", {
    "source": "user",
    "action": "message",
    "args": {"text": "hi"}
})

for i in range(5):
    time.sleep(1.5)
    evs = get(f"http://127.0.0.1:3000/api/v1/conversations/{conv_id}/events")["events"]
    print(f"Wait {i}, States: {[e.get('observation') or e.get('action') for e in evs]}")
    for e in evs:
        if e.get("observation") == "agent_state_changed" and e.get("extras", {}).get("agent_state") == "failed":
            print(f"FAILED. Full last event: {json.dumps(e, indent=2)}")
            sys.exit(1)
