"""Analyze all conversation runs for file creation stats."""
import requests

BASE = "http://localhost:3000/api/v1"

def get_all_events(cid):
    """Get all events, handling pagination."""
    all_events = []
    start_id = 0
    while True:
        r = requests.get(f"{BASE}/conversations/{cid}/events?start_id={start_id}", timeout=30)
        data = r.json()
        events = data.get("events", [])
        if not events:
            break
        all_events.extend(events)
        if not data.get("has_more", False):
            break
        start_id = events[-1]["id"] + 1
    return all_events

def analyze_conversation(cid):
    events = get_all_events(cid)
    n = len(events)
    paths = set()
    errors = 0
    stuck = 0
    incomplete = 0
    finish = False
    
    for e in events:
        obs = e.get("observation", "")
        action = e.get("action", "")
        content = str(e.get("content", ""))
        e.get("extras", {}) or {}
        
        # Check for file edits - look at the "File written:" message
        if "File written:" in content:
            # Extract path from "File written: <path> (<n> lines)"
            parts = content.split("File written: ")
            for part in parts[1:]:
                p = part.split(" (")[0].strip()
                if p:
                    paths.add(p.replace("/workspace/", "").lstrip("/"))
        
        if obs == "error":
            errors += 1
            if "STUCK" in content or "stuck" in content.lower():
                stuck += 1
            if "INCOMPLETE" in content:
                incomplete += 1
        
        if action == "finish":
            finish = True
    
    return {
        "events": n,
        "files": len(paths),
        "file_list": sorted(paths),
        "errors": errors,
        "stuck": stuck,
        "incomplete": incomplete,
        "finish": finish,
    }

# Get all conversations
r = requests.get(f"{BASE}/conversations", timeout=10)
all_convs = r.json()["results"]

for c in all_convs:
    cid = c["conversation_id"]
    status = c.get("status", "?")
    created = c.get("created_at", "?")[:19]
    
    stats = analyze_conversation(cid)
    
    print(f"{cid[:12]} | {status:8s} | {created} | events={stats['events']:4d} | files={stats['files']:2d} | errs={stats['errors']:3d} | stuck={stats['stuck']:2d} | incomplete={stats['incomplete']:2d} | finish={stats['finish']}")
    if stats["files"] > 0 and stats["files"] <= 30:
        print(f"  {stats['file_list']}")
