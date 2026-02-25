"""Quick smoke test: create a conversation, wait, check events."""
import json
import time
import urllib.request
import urllib.error

BASE = "http://localhost:3000"

def post(path, data):
    body = json.dumps(data).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=body,
                                  headers={"Content-Type": "application/json"},
                                  method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)

def get(path):
    req = urllib.request.Request(f"{BASE}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)

# Create conversation
resp = post("/api/v1/conversations", {"initial_user_msg": "say hello back please"})
cid = resp.get("conversation_id", "")
print(f"Created conversation: {cid}")
if not cid:
    print(f"ERROR: {resp}")
    exit(1)

# Poll events for up to 45 seconds
for i in range(9):
    time.sleep(5)
    data = get(f"/api/v1/conversations/{cid}/events")
    events = data.get("events", [])
    last = events[-1] if events else {}
    print(f"  [{i}] events={len(events)} last_action={last.get('action','')} "
          f"last_obs={last.get('observation','')} "
          f"state={last.get('extras',{}).get('agent_state','')}")
    if last.get("observation") == "agent_state_changed" and "awaiting_user" in str(last.get("extras",{})):
        print("  -> Agent returned to AWAITING_USER_INPUT (response delivered!)")
        break
    if last.get("action") == "message" and last.get("source") == "agent":
        print(f"  -> Agent message: {str(last.get('message',''))[:200]}")
        break

print("\nFinal events:")
data = get(f"/api/v1/conversations/{cid}/events")
for ev in data.get("events", []):
    msg_preview = str(ev.get("message",""))[:80]
    print(f"  id={ev['id']} action={ev.get('action','')} obs={ev.get('observation','')} "
          f"state={ev.get('extras',{}).get('agent_state','')} msg={msg_preview!r}")
