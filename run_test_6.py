#!/usr/bin/env python3
"""Test 6: Verify /workspace path fix — mkdir should only be called once."""
import sys
import time
import json
import urllib.request
import urllib.error

BASE = "http://localhost:3000"

def api(method, path, body=None, content_type="application/json"):
    url = BASE + path
    data = (json.dumps(body).encode() if content_type == "application/json" and body is not None
            else body.encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}


def main():
    print("=== Test 6: /workspace path fix ===\n")

    # 1. Create conversation
    conv = api("POST", "/api/v1/conversations", {})
    cid = conv.get("conversation_id")
    print(f"Conversation: {cid}")

    # 2. Wait for runtime ready
    for _ in range(20):
        state = api("GET", f"/api/v1/conversations/{cid}")
        if state.get("agent_state") == "awaiting_user_input":
            break
        time.sleep(1)
    print(f"Agent state before send: {state.get('agent_state')}")

    # 3. Send task
    task = ("Create a Python URL shortener with exactly 5 files: "
            "app.py, models.py, database.py, templates/index.html, and tests/test_app.py")
    resp = api("POST", f"/api/v1/conversations/{cid}/events/raw",
               body=task, content_type="text/plain")
    print(f"Send response: {resp}")

    # 4. Poll until done
    print("\nPolling for completion...")
    start = time.time()
    for i in range(120):
        time.sleep(2)
        state = api("GET", f"/api/v1/conversations/{cid}")
        agent_state = state.get("agent_state", "unknown")
        elapsed = int(time.time() - start)
        if i % 5 == 0:
            print(f"  t={elapsed}s  state={agent_state}")
        if agent_state in ("awaiting_user_input", "error", "stopped", "finished"):
            print(f"\nDone! Final state: {agent_state} ({elapsed}s)")
            break

    # 5. Inspect events
    events_resp = api("GET", f"/api/v1/conversations/{cid}/events?limit=100")
    events = events_resp.get("events", [])
    print(f"\nTotal events: {len(events)}")

    # Count mkdir calls and check for /workspace references
    mkdir_count = 0
    wrong_workspace = 0
    files_created = []
    
    for e in events:
        action = e.get("action", "")
        args = e.get("args", {})
        cmd = args.get("command", "")
        path = args.get("path", "")
        
        if "mkdir" in cmd:
            mkdir_count += 1
            print(f"  mkdir call: {cmd!r}")
        
        if "/workspace" in cmd and "C:\\workspace" in cmd:
            wrong_workspace += 1
            print(f"  WRONG WORKSPACE in cmd: {cmd!r}")
        
        if action in ("write", "edit") and path:
            if "FORGE_workspace" in path or (not path.startswith("/workspace") and path):
                files_created.append(path)

    print(f"\nResults:")
    print(f"  mkdir calls: {mkdir_count} (ideal: 1)")
    print(f"  wrong /workspace references: {wrong_workspace} (ideal: 0)")
    print(f"  files created (detected): {len(files_created)}")
    for f in files_created:
        print(f"    - {f}")

    print(f"\nConversation ID: {cid}")
    print(f"Run: python inspect_events.py {cid}")


if __name__ == "__main__":
    main()
