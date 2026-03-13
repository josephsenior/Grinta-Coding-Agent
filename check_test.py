import requests
import os

CID = "ab303714f5734050b0782c8ea9d53eb0"
BASE = "http://localhost:3000/api/v1"

# Get conversation state
try:
    conv = requests.get(f"{BASE}/conversations/{CID}").json()
    state = conv.get("state", "?")
except:  # noqa: E722
    state = "unknown"
print(f"State: {state}")

# Get events
resp = requests.get(f"{BASE}/conversations/{CID}/events", params={"limit": 5000}).json()
events = resp.get("events", resp) if isinstance(resp, dict) else resp
# Filter to only dicts
events = [e for e in events if isinstance(e, dict)]
print(f"Total events: {len(events)}")

# Count file edit observations  
edit_obs_paths = []
for e in events:
    obs = e.get("observation", "")
    if obs == "edit":
        path = e.get("extras", {}).get("path", "") or e.get("args", {}).get("path", "")
        edit_obs_paths.append(path)

# Count file edit actions
action_paths = []
for e in events:
    action = e.get("action", "")
    if action == "edit":
        path = e.get("args", {}).get("path", "")
        if path:
            action_paths.append(path)

unique_action_paths = set(action_paths)
print(f"File edit actions: {len(action_paths)} total, {len(unique_action_paths)} unique")
print(f"File edit observations: {len(edit_obs_paths)}")

# Count errors
errors = [e for e in events if e.get("observation", "") == "error"]
print(f"Error events: {len(errors)}")

# Check for "already exists" messages
already_exists = [e for e in events if "already exists" in str(e.get("content", ""))]
print(f"'Already exists' responses: {len(already_exists)}")

# Show unique file paths
print("\nUnique files edited (by basename):")
for p in sorted(set(os.path.basename(p) for p in unique_action_paths if p)):
    print(f"  {p}")

# Show last 5 events summary
print("\nLast 5 events:")
for e in events[-5:]:
    action = e.get("action", "")
    obs = e.get("observation", "")
    content = str(e.get("content", "") or "")[:120]
    path = e.get("args", {}).get("path", "") or e.get("extras", {}).get("path", "")
    eid = e.get("id", "?")
    if action:
        print(f"  [{eid}] ACTION: {action} path={path}")
    elif obs:
        print(f"  [{eid}] OBS: {obs} | {content}")
    else:
        print(f"  [{eid}] ???")
