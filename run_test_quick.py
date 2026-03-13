#!/usr/bin/env python3
"""Quick test: Create hello.py and check denormalization."""
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://localhost:3000"

def api(method, path, body=None, ct="application/json"):
    url = BASE + path
    data = (json.dumps(body).encode() if ct == "application/json" and body is not None
            else body.encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": ct})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}

conv = api("POST", "/api/v1/conversations", {})
print(f"Raw response: {conv}")
cid = conv.get("conversation_id")
if not cid:
    print("ERROR: No conversation_id in response. Exiting.")
    sys.exit(1)
print(f"Conv: {cid}")

for _ in range(20):
    state = api("GET", f"/api/v1/conversations/{cid}")
    if state.get("agent_state") == "awaiting_user_input":
        break
    time.sleep(1)
print(f"State: {state.get('agent_state')}")

resp = api("POST", f"/api/v1/conversations/{cid}/events/raw",
           body="Create a file called hello.py that prints hello world. Just create that one file, nothing else.",
           ct="text/plain")
print(f"Sent: {resp}")

start = time.time()
for i in range(60):
    time.sleep(3)
    state = api("GET", f"/api/v1/conversations/{cid}")
    agent_state = state.get("agent_state", "unknown")
    elapsed = int(time.time() - start)
    if i % 5 == 0:
        print(f"  t={elapsed}s state={agent_state}")
    if agent_state in ("awaiting_user_input", "error", "stopped", "finished"):
        print(f"Done! {agent_state} ({elapsed}s)")
        break
else:
    print(f"TIMEOUT after {int(time.time()-start)}s")

print(f"\nConv ID: {cid}")
print(f"Inspect: python inspect_events.py {cid} 7 30")
