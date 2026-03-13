"""Check test results for the latest conversation."""
import json
import urllib.request

def api(method, path):
    url = f"http://localhost:3000{path}"
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def main():
    convs = api("GET", "/api/v1/conversations")
    if not convs:
        print("No conversations found")
        return

    # Find latest conversation
    cid = "2e275ff29ee84161ad1eeba432abf320"
    found = any(c.get("conversation_id") == cid for c in convs)
    if not found:
        # Use the most recent one
        cid = convs[0].get("conversation_id", "")
        print(f"Using latest conversation: {cid}")

    state = api("GET", f"/api/v1/conversations/{cid}")
    print(f"State: {state.get('agent_state')}")

    events_resp = api("GET", f"/api/v1/conversations/{cid}/events?limit=500")
    events = events_resp.get("events", [])
    print(f"Total events: {len(events)}")

    files_created = set()
    tool_calls = 0
    errors = 0
    finish_called = False
    bash_cmds = 0
    bash_errors = 0

    for e in events:
        action = e.get("action", "")
        args = e.get("args", {})
        source = e.get("source", "")
        obs = e.get("observation", "")

        if source == "agent":
            if action in ("execute_bash", "str_replace_editor", "write"):
                tool_calls += 1
            if action == "execute_bash":
                bash_cmds += 1

        path = args.get("path", "")
        cmd = args.get("command", "")

        if cmd == "create" and path:
            files_created.add(path)
        elif action == "write" and path:
            files_created.add(path)

        if obs == "error":
            errors += 1
            if action == "execute_bash":
                bash_errors += 1

        if action == "finish":
            finish_called = True

    print("\nResults:")
    print(f"  Tool calls: {tool_calls}")
    print(f"  Bash commands: {bash_cmds}")
    print(f"  Bash errors: {bash_errors}")
    print(f"  Files created: {len(files_created)} / 24 target")
    print(f"  Total errors: {errors}")
    print(f"  Finish called: {finish_called}")

    if files_created:
        print("\n  Created files:")
        for f in sorted(files_created):
            print(f"    - {f}")

    # Show last few events to understand what happened at the end
    print("\nLast 5 events:")
    for e in events[-5:]:
        action = e.get("action", "")
        obs = e.get("observation", "")
        source = e.get("source", "")
        args = e.get("args", {})
        content = str(args.get("command", args.get("path", args.get("thought", ""))))[:100]
        print(f"  [{source}] {action} {obs} | {content}")

if __name__ == "__main__":
    main()
