#!/usr/bin/env python3
"""Complex test: Full Next.js TypeScript restaurant management app with auth."""
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:3000"

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
        except (urllib.error.HTTPError) as e:
            return {"error": e.code, "body": e.read().decode()}
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < 2:
                time.sleep(5)
                continue
            return {"error": "connection_failed", "detail": str(e)}


def main():
    print("=== Complex Test: Next.js Restaurant Management App ===\n")

    # 1. Create conversation
    conv = api("POST", "/api/v1/conversations", {})
    cid = conv.get("conversation_id")
    if not cid:
        print(f"ERROR: No conversation_id. Response: {conv}")
        sys.exit(1)
    print(f"Conversation: {cid}")

    # 2. Wait for runtime ready
    for _ in range(30):
        state = api("GET", f"/api/v1/conversations/{cid}")
        if state.get("agent_state") == "awaiting_user_input":
            break
        time.sleep(1)
    print(f"Agent state: {state.get('agent_state')}")

    # 3. Send task
    resp = api("POST", f"/api/v1/conversations/{cid}/events/raw",
               body=TASK, ct="text/plain")
    print(f"Sent: {resp}")

    # 4. Poll until done (longer timeout for complex task)
    print("\nPolling for completion...")
    start = time.time()
    last_state = "unknown"
    for i in range(300):  # 10 min max
        time.sleep(2)
        state = api("GET", f"/api/v1/conversations/{cid}")
        if state.get("error") == "connection_failed":
            elapsed = int(time.time() - start)
            print(f"  t={elapsed}s  connection lost, retrying...")
            continue
        agent_state = state.get("agent_state", "unknown")
        elapsed = int(time.time() - start)
        if agent_state != last_state or i % 15 == 0:
            print(f"  t={elapsed}s  state={agent_state}")
            last_state = agent_state
        if agent_state in ("awaiting_user_input", "stopped", "finished"):
            print(f"\nDone! Final state: {agent_state} ({elapsed}s)")
            break
        # Allow transient error states — agent may recover via retry
        if agent_state in ("error", None) and elapsed > 120:
            print(f"\nDone! Final state: {agent_state} ({elapsed}s)")
            break
    else:
        elapsed = int(time.time() - start)
        print(f"\nTIMEOUT after {elapsed}s (state={last_state})")

    # 5. Analyze events
    events = []
    for page_start in range(0, 1000, 100):
        events_resp = api("GET", f"/api/v1/conversations/{cid}/events?limit=100&start={page_start}")
        batch = events_resp.get("events", [])
        if not batch:
            break
        events.extend(batch)
    print(f"\nTotal events: {len(events)}")

    # Count file creations
    files_created = set()
    tool_calls = 0
    errors = 0
    finish_called = False

    for e in events:
        action = e.get("action", "")
        args = e.get("args", {})
        source = e.get("source", "")

        # Count tool calls from agent
        if source == "agent" and action in ("execute_bash", "str_replace_editor", "write"):
            tool_calls += 1

        # Track file creations
        path = args.get("path", "")
        cmd = args.get("command", "")
        args.get("file_text", "")

        if cmd == "create" and path:
            files_created.add(path)
        elif action == "write" and path:
            files_created.add(path)

        # Count errors
        if "error" in str(e.get("observation", "")).lower():
            errors += 1

        if action == "finish":
            finish_called = True

    print("\nResults:")
    print(f"  Tool calls: {tool_calls}")
    print(f"  Files created: {len(files_created)} / 24 target")
    print(f"  Errors encountered: {errors}")
    print(f"  Finish called: {finish_called}")

    if files_created:
        print("\n  Files:")
        for f in sorted(files_created):
            print(f"    - {f}")

    print(f"\nConversation ID: {cid}")
    print(f"Inspect: python inspect_events.py {cid} 7 50")


if __name__ == "__main__":
    main()
