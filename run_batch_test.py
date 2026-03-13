#!/usr/bin/env python3
"""Run the Next.js test N times and report aggregate statistics."""
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:3000"
NUM_RUNS = 5
TARGET_FILES = 24

TASK = """Create a full-stack restaurant management application using Next.js 14 with TypeScript and the App Router. The project should include authentication. Here are the exact files to create:

1. package.json — with dependencies: next, react, react-dom, typescript, next-auth, prisma, @prisma/client, bcryptjs, zod
2. tsconfig.json — standard Next.js TypeScript config
3. next.config.js — Next.js configuration
4. prisma/schema.prisma — Prisma schema with User, Restaurant, MenuItem, Order, and OrderItem models
5. src/app/layout.tsx — Root layout with SessionProvider wrapper
6. src/app/page.tsx — Landing page with hero section and navigation
7. src/app/globals.css — Global styles with Tailwind-like utility classes
8. src/app/api/auth/[...nextauth]/route.ts — NextAuth configuration with credentials provider
9. src/app/api/restaurants/route.ts — REST API for CRUD restaurants (GET, POST)
10. src/app/api/menu/route.ts — REST API for menu items (GET, POST)
11. src/app/api/orders/route.ts — REST API for orders (GET, POST)
12. src/app/dashboard/page.tsx — Dashboard page showing restaurants and stats
13. src/app/menu/page.tsx — Menu management page with add/edit/delete
14. src/app/orders/page.tsx — Orders page with status tracking
15. src/app/auth/login/page.tsx — Login page with form
16. src/app/auth/register/page.tsx — Registration page with form
17. src/lib/prisma.ts — Prisma client singleton
18. src/lib/auth.ts — Auth utilities and session helpers
19. src/components/Navbar.tsx — Navigation bar with auth state
20. src/components/RestaurantCard.tsx — Restaurant display card component
21. src/components/MenuItemForm.tsx — Form component for adding/editing menu items
22. src/components/OrderTable.tsx — Table component for displaying orders
23. src/middleware.ts — NextAuth middleware for protected routes
24. .env.example — Environment variables template

Create all 24 files with complete, working TypeScript code. Each file should have proper imports, types, and error handling."""


def api(method, path, body=None, ct="application/json"):
    url = BASE + path
    data = (json.dumps(body).encode() if ct == "application/json" and body is not None
            else body.encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, method=method,
                                headers={"Content-Type": ct})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return {"error": e.code, "body": e.read().decode()}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < 2:
                time.sleep(5)
                continue
            return {"error": "connection_failed", "detail": str(e)}


def run_single_test(run_num: int) -> dict:
    """Run a single test and return results dict."""
    print(f"\n{'='*60}")
    print(f"  RUN {run_num}/{NUM_RUNS}")
    print(f"{'='*60}")

    # Create conversation
    conv = api("POST", "/api/v1/conversations", {})
    cid = conv.get("conversation_id")
    if not cid:
        print(f"  ERROR: No conversation_id. Response: {conv}")
        return {"cid": None, "files": 0, "errors": -1, "state": "error", "time": 0, "events": 0, "finish": False}

    print(f"  CID: {cid}")

    # Wait for runtime ready
    for _ in range(30):
        state = api("GET", f"/api/v1/conversations/{cid}")
        if state.get("agent_state") == "awaiting_user_input":
            break
        time.sleep(1)

    # Send task
    api("POST", f"/api/v1/conversations/{cid}/events/raw", body=TASK, ct="text/plain")

    # Poll until done
    start = time.time()
    last_state = "unknown"
    final_state = "timeout"
    for i in range(300):
        time.sleep(2)
        state = api("GET", f"/api/v1/conversations/{cid}")
        if state.get("error") == "connection_failed":
            continue
        agent_state = state.get("agent_state", "unknown")
        elapsed = int(time.time() - start)
        if agent_state != last_state:
            print(f"  t={elapsed}s state={agent_state}")
            last_state = agent_state
        if agent_state in ("awaiting_user_input", "stopped", "finished"):
            final_state = agent_state
            break
        if agent_state in ("error", None, "rate_limited") and elapsed > 120:
            final_state = agent_state or "error"
            break
        if agent_state == "running" and elapsed > 300:
            print(f"  t={elapsed}s TIMEOUT — still running after 300s")
            final_state = "timeout"
            break

    elapsed = int(time.time() - start)

    # Stop the conversation if it's still running (timeout / rate_limited)
    if final_state in ("timeout", "rate_limited"):
        api("POST", f"/api/v1/conversations/{cid}/config",
            {"agent_state": "stopped"})
        time.sleep(2)

    # Analyze events (paginate using start_id)
    events = []
    start_id = 0
    while len(events) < 5000:
        events_resp = api("GET", f"/api/v1/conversations/{cid}/events?start_id={start_id}")
        batch = events_resp.get("events", [])
        if not batch:
            break
        events.extend(batch)
        if not events_resp.get("has_more", False):
            break
        start_id = batch[-1]["id"] + 1

    # Count files using "File written:" in content
    files_created = set()
    errors = 0
    finish_called = False
    stuck_count = 0
    incomplete_count = 0

    for e in events:
        content = str(e.get("content", ""))
        action = e.get("action", "")
        obs = e.get("observation", "")

        if "File written:" in content:
            parts = content.split("File written: ")
            for part in parts[1:]:
                p = part.split(" (")[0].strip()
                if p:
                    files_created.add(p.replace("/workspace/", "").lstrip("/"))

        if obs == "error":
            errors += 1
            if "STUCK" in content or "stuck" in content.lower():
                stuck_count += 1
            if "INCOMPLETE" in content:
                incomplete_count += 1

        if action == "finish":
            finish_called = True

    result = {
        "cid": cid,
        "files": len(files_created),
        "file_list": sorted(files_created),
        "errors": errors,
        "stuck": stuck_count,
        "incomplete": incomplete_count,
        "state": final_state,
        "time": elapsed,
        "events": len(events),
        "finish": finish_called,
    }

    # PASS = all target files created and conversation reached a terminal state
    # Stuck detection errors are recoverable and don't count as failures
    is_pass = (result["files"] == TARGET_FILES and 
               final_state in ("finished", "awaiting_user_input"))
    status = "PASS" if is_pass else "FAIL"
    print(f"  Result: {status} — {result['files']}/{TARGET_FILES} files, {result['errors']} errors, "
          f"{result['events']} events, {elapsed}s, state={final_state}")

    return result


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else NUM_RUNS
    print(f"Running {n} consistency tests against {BASE}")
    print(f"Target: {TARGET_FILES} files per run, 0 errors\n")

    results = []
    i = 1
    rate_limit_retries = 0
    max_rate_retries = 3  # Max retries per run for rate limiting
    while i <= n:
        r = run_single_test(i)
        if r["state"] == "rate_limited" and rate_limit_retries < max_rate_retries:
            rate_limit_retries += 1
            wait = 120 * rate_limit_retries  # Exponential: 120s, 240s, 360s
            print(f"  Rate limited (retry {rate_limit_retries}/{max_rate_retries}) — waiting {wait}s...")
            time.sleep(wait)
            continue  # Retry same run number
        rate_limit_retries = 0
        results.append(r)
        if i < n:
            if r["state"] == "rate_limited":
                print("  Rate limited — giving up retries, moving on after 120s...")
                time.sleep(120)
            else:
                print("  Waiting 10s before next run...")
                time.sleep(10)
        i += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"  SUMMARY: {n} runs")
    print(f"{'='*60}")

    passes = sum(1 for r in results if r["files"] == TARGET_FILES and 
                r["state"] in ("finished", "awaiting_user_input"))
    files_list = [r["files"] for r in results]
    errors_list = [r["errors"] for r in results]
    times_list = [r["time"] for r in results if r["time"] > 0]
    events_list = [r["events"] for r in results]

    print(f"\n  Pass rate: {passes}/{n} ({passes/n*100:.0f}%)")
    print(f"  Files:  min={min(files_list)}, max={max(files_list)}, avg={sum(files_list)/len(files_list):.1f}")
    print(f"  Errors: min={min(errors_list)}, max={max(errors_list)}, avg={sum(errors_list)/len(errors_list):.1f}")
    if times_list:
        print(f"  Time:   min={min(times_list)}s, max={max(times_list)}s, avg={sum(times_list)/len(times_list):.0f}s")
    print(f"  Events: min={min(events_list)}, max={max(events_list)}, avg={sum(events_list)/len(events_list):.0f}")

    print("\n  Per-run details:")
    for i, r in enumerate(results, 1):
        status = ("PASS" if r["files"] == TARGET_FILES and 
                  r["state"] in ("finished", "awaiting_user_input") else "FAIL")
        print(f"    Run {i}: {status} | files={r['files']}/{TARGET_FILES} | errs={r['errors']} | "
              f"stuck={r['stuck']} | t={r['time']}s | events={r['events']} | state={r['state']} | finish={r['finish']}")

    # Missing files breakdown for any FAIL runs
    failed = [r for r in results if r["files"] < TARGET_FILES]
    if failed:
        print("\n  Missing files in failed runs:")
        expected = {
            ".env.example", "next.config.js", "package.json", "prisma/schema.prisma",
            "src/app/api/auth/[...nextauth]/route.ts", "src/app/api/menu/route.ts",
            "src/app/api/orders/route.ts", "src/app/api/restaurants/route.ts",
            "src/app/auth/login/page.tsx", "src/app/auth/register/page.tsx",
            "src/app/dashboard/page.tsx", "src/app/globals.css", "src/app/layout.tsx",
            "src/app/menu/page.tsx", "src/app/orders/page.tsx", "src/app/page.tsx",
            "src/components/MenuItemForm.tsx", "src/components/Navbar.tsx",
            "src/components/OrderTable.tsx", "src/components/RestaurantCard.tsx",
            "src/lib/auth.ts", "src/lib/prisma.ts", "src/middleware.ts", "tsconfig.json",
        }
        for i, r in enumerate(results, 1):
            if r["files"] < TARGET_FILES:
                missing = expected - set(r["file_list"])
                print(f"    Run {i}: missing {sorted(missing)}")

    return 0 if passes == n else 1


if __name__ == "__main__":
    sys.exit(main())
