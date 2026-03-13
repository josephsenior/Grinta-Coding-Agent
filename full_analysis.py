"""Comprehensive analysis of all conversations with categorization."""
import requests

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

def main():
    r = requests.get(f"{BASE}/conversations")
    data = r.json()
    convs = data if isinstance(data, list) else data.get("results", data.get("conversations", []))
    convs = list(convs)

    results = []
    for c in convs:
        cid = c["conversation_id"]
        state = c.get("status", "?")
        events = get_events(cid)

        files_created = set()
        errors = 0
        stuck = 0
        for ev in events:
            obs = ev.get("observation", "")
            extras = ev.get("extras", {}) or {}
            content = str(ev.get("content", ""))
            if obs == "write" and "path" in extras:
                files_created.add(extras["path"])
            if obs == "error":
                errors += 1
                if "stuck" in content.lower() or "STUCK" in content:
                    stuck += 1

        cat = "UNKNOWN"
        if len(events) == 0:
            cat = "NO_DATA"
        elif len(events) <= 12 and errors == 0:
            cat = "RATE_LIM"
        elif len(events) <= 22 and errors >= 5:
            cat = "CRASH"
        elif len(files_created) >= 24 and state in ("stopped", "finished"):
            cat = "PASS"
        elif len(files_created) >= 20:
            cat = "PARTIAL+"
        elif len(files_created) >= 1:
            cat = "PARTIAL"

        results.append({
            "cid": cid[:12], "state": state, "files": len(files_created),
            "errors": errors, "stuck": stuck, "events": len(events), "cat": cat
        })

    header = f"{'CID':>12} | {'State':>10} | {'Files':>7} | {'Err':>3} | {'Stk':>3} | {'Evts':>5} | Category"
    print(header)
    print("-" * 70)
    for r in results:
        print(f"{r['cid']:>12} | {r['state']:>10} | {r['files']:2d}/24   | {r['errors']:3d} | {r['stuck']:3d} | {r['events']:5d} | {r['cat']}")

    passes = sum(1 for r in results if r["cat"] == "PASS")
    total_valid = sum(1 for r in results if r["cat"] not in ("RATE_LIM", "CRASH", "NO_DATA"))
    rate_lim = sum(1 for r in results if r["cat"] == "RATE_LIM")
    crash = sum(1 for r in results if r["cat"] == "CRASH")
    no_data = sum(1 for r in results if r["cat"] == "NO_DATA")

    pct = passes / total_valid * 100 if total_valid > 0 else 0
    print(f"\nPASS: {passes}/{total_valid} valid runs ({pct:.0f}% success)")
    print(f"(Excluded: {rate_lim} rate-limited, {crash} crashed, {no_data} no-data)")

if __name__ == "__main__":
    main()
