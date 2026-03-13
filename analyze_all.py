"""Analyze all conversations for file creation results."""
import requests
import sys

BASE = "http://localhost:3000/api/v1"

def get_events(cid):
    all_events = []
    start_id = 0
    while True:
        try:
            r = requests.get(f"{BASE}/conversations/{cid}/events", params={"start_id": start_id}, timeout=10)
        except Exception:
            break
        if r.status_code != 200:
            break
        data = r.json()
        events = data.get("events", data) if isinstance(data, dict) else data
        if not events or not isinstance(events, list):
            break
        all_events.extend(events)
        if isinstance(data, dict) and data.get("has_more"):
            start_id = events[-1].get("id", 0) + 1
        else:
            break
    return all_events

def analyze():
    r = requests.get(f"{BASE}/conversations")
    data = r.json()
    convs = data if isinstance(data, list) else data.get("results", data.get("conversations", []))
    convs = list(convs)

    print(f"{'CID':>12} | {'State':>12} | {'Files':>7} | {'Errors':>6} | {'Events':>6}")
    print("-" * 60)

    for c in convs:
        cid = c["conversation_id"]
        state = c.get("status", "?")

        events = get_events(cid)

        files_created = set()
        errors = 0
        for ev in events:
            obs = ev.get("observation", "")
            extras = ev.get("extras", {}) or {}
            if obs == "write" and "path" in extras:
                files_created.add(extras["path"])
            if obs == "error":
                errors += 1

        print(f"{cid[:12]:>12} | {state:>12} | {len(files_created):2d}/24   | {errors:5d}  | {len(events):5d}")

    print()
    print("Legend:")
    print("  Rate-limited runs: 0/24 files, 0 errors, ~12 events")
    print("  Crashed runs: 0/24 files, 5+ errors, ~19 events")
    print("  Pre-fix runs: 12-16/24 files")
    print("  Post-fix runs: 24+/24 files (31 = file re-creates counted)")

if __name__ == "__main__":
    analyze()
