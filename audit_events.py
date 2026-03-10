"""Monitor conversation events for auditing agent behavior."""
import requests
import time
import sys

CONV_ID = sys.argv[1] if len(sys.argv) > 1 else "2eb393fba52b408680f5103caf1707cf"
BASE = "http://localhost:3000/api/v1/conversations"
TIMEOUT = 300  # 5 minutes

seen = 0
start_time = time.time()
file_writes = 0
total_events = 0
tool_calls = {}
first_file_write_event = None

print(f"Monitoring conversation {CONV_ID}...")
print(f"{'Time':>7s} {'#':>4s} {'Source':10s} {'Type':30s} Detail")
print("-" * 100)

while True:
    try:
        r = requests.get(
            f"{BASE}/{CONV_ID}/events",
            params={"start_id": seen, "limit": 50},
            timeout=10,
        )
        data = r.json()
        events = data.get("events", [])

        for e in events:
            eid = e.get("id", 0)
            etype = e.get("event_type", e.get("action", "?"))
            source = e.get("source", "?")
            elapsed = time.time() - start_time
            total_events += 1

            # Extract key info
            detail = ""
            args = e.get("args", {})
            if "tool" in args:
                tool_name = args["tool"]
                detail = f"tool={tool_name}"
                tool_calls[tool_name] = tool_calls.get(tool_name, 0) + 1
            elif "command" in args and isinstance(args["command"], str):
                detail = f"cmd={args['command'][:80]}"
            elif "path" in args:
                detail = f"path={args['path']}"
            elif "thought" in args:
                detail = f"thought={str(args['thought'])[:80]}"
            elif "content" in args:
                detail = f"content={str(args['content'])[:80]}"
            elif "outputs" in args:
                detail = f"output={str(args['outputs'])[:80]}"

            # Track file writes
            if etype in ("FileWriteAction", "FileEditAction", "write"):
                file_writes += 1
                if first_file_write_event is None:
                    first_file_write_event = eid
            if "file_text" in args or ("command" in args and args.get("command") == "create"):
                file_writes += 1
                if first_file_write_event is None:
                    first_file_write_event = eid

            print(f"[{elapsed:6.1f}s] #{eid:3d} {source:10s} {etype:30s} {detail}")
            seen = eid + 1

        if not events:
            time.sleep(2)

        if time.time() - start_time > TIMEOUT:
            print("\n--- 5 min timeout ---")
            break

    except KeyboardInterrupt:
        break
    except Exception as ex:
        print(f"Error: {ex}")
        time.sleep(3)

# Summary
print("\n" + "=" * 100)
print("AUDIT SUMMARY")
print("=" * 100)
print(f"Total events:          {total_events}")
print(f"File writes:           {file_writes}")
print(f"First file write at:   event #{first_file_write_event or 'NONE'}")
print(f"Tool call distribution:")
for tool, count in sorted(tool_calls.items(), key=lambda x: -x[1]):
    print(f"  {tool:30s} {count}x")
print(f"Elapsed time:          {time.time() - start_time:.1f}s")
