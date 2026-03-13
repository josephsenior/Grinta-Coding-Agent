"""Integration test: verify stuck loop detection and condensation objective preservation."""
import os
import time

import requests

BASE = "http://localhost:3000"
API = f"{BASE}/api/v1"
HEADERS = {"Content-Type": "application/json"}

def create_conversation():
    r = requests.post(f"{API}/conversations", json={}, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()["conversation_id"]

def send_message(cid, msg):
    payload = {
        "action": "message",
        "args": {"content": msg, "wait_for_response": False},
    }
    r = requests.post(
        f"{API}/conversations/{cid}/messages",
        json=payload,
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def get_events(cid, start=0):
    try:
        r = requests.get(
            f"{API}/conversations/{cid}/events?start={start}",
            headers=HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return []

def wait_for_completion(cid, max_wait=300):
    """Wait for agent to reach a terminal state."""
    start = time.time()
    last_event_count = 0
    stale_count = 0
    while time.time() - start < max_wait:
        events = get_events(cid, 0)
        if not events:
            time.sleep(3)
            continue
        count = len(events)
        # Check if agent finished or errored
        for ev in events[-5:]:
            obs = ev.get("observation", "")
            if obs in ("agent_state_changed",):
                extras = ev.get("extras", {})
                state = extras.get("agent_state", "")
                if state in ("stopped", "error", "finished"):
                    return events
        if count == last_event_count:
            stale_count += 1
            if stale_count > 20:
                return events
        else:
            stale_count = 0
            last_event_count = count
        time.sleep(3)
    return get_events(cid, 0)


def analyze_events(events):
    """Analyze events for issues."""
    results = {
        "total_events": len(events),
        "write_count": 0,
        "read_count": 0,
        "ls_count": 0,
        "stuck_messages": 0,
        "condensation_count": 0,
        "condensation_summaries": [],
        "agent_finished": False,
        "agent_errored": False,
    }
    for ev in events:
        action = ev.get("action", "")
        obs = ev.get("observation", "")
        content = ev.get("content", "") or ""
        args = ev.get("args", {})
        cmd = args.get("command", "") or ""
        cmd_lower = cmd.lower()
        
        if action == "write":
            results["write_count"] += 1
        elif action == "run" and ("ls " in cmd_lower or "dir " in cmd_lower or "get-childitem" in cmd_lower or "tree" in cmd_lower):
            results["ls_count"] += 1
        elif action == "run" and ("get-content" in cmd_lower or "cat " in cmd_lower or "type " in cmd_lower):
            results["read_count"] += 1
            
        if obs == "agent_condensation":
            results["condensation_count"] += 1
            results["condensation_summaries"].append(content[:200] if content else "")
            
        if "STUCK LOOP DETECTED" in content:
            results["stuck_messages"] += 1
            
        if obs == "agent_state_changed":
            extras = ev.get("extras", {})
            state = extras.get("agent_state", "")
            if state == "finished":
                results["agent_finished"] = True
            elif state == "error":
                results["agent_errored"] = True
    return results


if __name__ == "__main__":
    print("=== Integration Test: Stuck Loop & Condensation Fix ===")
    
    cid = create_conversation()
    print(f"Conversation: {cid}")
    
    # Simple task that should NOT cause verification loops
    send_message(cid, "Create a Python file called hello.py that prints 'Hello World' and a file called goodbye.py that prints 'Goodbye World'. That's it, just create those two files.")
    print("Message sent, waiting for completion...")
    
    events = wait_for_completion(cid, max_wait=180)
    results = analyze_events(events)
    
    print("\n=== Results ===")
    print(f"Total events: {results['total_events']}")
    print(f"File writes: {results['write_count']}")
    print(f"ls/dir commands: {results['ls_count']}")
    print(f"read commands: {results['read_count']}")
    print(f"Stuck messages: {results['stuck_messages']}")
    print(f"Condensation count: {results['condensation_count']}")
    print(f"Agent finished: {results['agent_finished']}")
    print(f"Agent errored: {results['agent_errored']}")
    
    # Check ratios
    total_reads = results['ls_count'] + results['read_count']
    writes = results['write_count']
    
    print(f"\nRead/Write ratio: {total_reads}:{writes}")
    
    if results['condensation_count'] > 0:
        print("\nCondensation summaries:")
        for i, s in enumerate(results['condensation_summaries']):
            print(f"  [{i}]: {s}")
    
    # Assertions
    issues = []
    if results['total_events'] == 0:
        issues.append("No events returned (API may be unresponsive)")
    if total_reads > 20 and writes > 0 and total_reads / writes > 10:
        issues.append(f"Excessive read/write ratio: {total_reads}:{writes}")
    if results['stuck_messages'] > 0 and not results['agent_finished'] and not results['agent_errored']:
        issues.append("Stuck detected but agent neither finished nor errored")
    
    if issues:
        print(f"\n!!! ISSUES: {issues}")
    else:
        print("\n--- All checks passed ---")
    
    # Also scan disk events for path leaks
    conv_dir = os.path.join(
        "storage", "users", "oss_user", "conversations", cid, "events"
    )
    if os.path.isdir(conv_dir):
        leak_count = 0
        for fname in os.listdir(conv_dir):
            if fname.endswith(".json"):
                with open(os.path.join(conv_dir, fname), "r", encoding="utf-8") as f:
                    text = f.read()
                if "FORGE_workspace" in text or "AppData\\Local\\Temp\\FORGE" in text:
                    leak_count += 1
        print(f"\nPath leak scan: {leak_count} events with leaks out of {len(os.listdir(conv_dir))}")
    else:
        print(f"\nEvent directory not found: {conv_dir}")
