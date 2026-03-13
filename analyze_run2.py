"""Analyze test run events in detail."""
import json
import os
import sys

cid = sys.argv[1] if len(sys.argv) > 1 else "1e69226aefab48f1b2db2f719aff6aee"
events_dir = os.path.join(
    r"C:\Users\GIGABYTE\Desktop\Forge\storage\users\oss_user\conversations",
    cid, "events"
)

files_created = set()
bash_cmds = 0
bash_ok = 0
bash_err = 0
tool_calls = 0
stuck_count = 0
bash_error_cmds = []
create_events = []

event_files = sorted(os.listdir(events_dir), key=lambda x: int(x.split(".")[0]))

for fname in event_files:
    with open(os.path.join(events_dir, fname)) as f:
        e = json.load(f)

    eid = e.get("id", "?")
    action = e.get("action", "")
    args = e.get("args", {})
    source = e.get("source", "")
    obs = e.get("observation", "")
    content = e.get("content", "")
    extras = e.get("extras", {})
    tcm = e.get("tool_call_metadata", {})
    fn = tcm.get("function_name", "")

    # Track tool calls (using function_name from tool_call_metadata)
    if source == "agent" and fn:
        tool_calls += 1
    if source == "agent" and fn == "execute_bash":
        bash_cmds += 1

    # Track command outputs (action="run" obs="" from env, or check exit_code)
    if source == "environment" and action == "" and obs == "run":
        meta = extras.get("metadata", {})
        exit_code = meta.get("exit_code", -1)
        if exit_code == 0:
            bash_ok += 1
        elif exit_code > 0:
            bash_err += 1
            bash_error_cmds.append((eid, exit_code, content[:150]))

    # Track file creations (action="write" means file created by editor)
    if action == "write" and source == "agent":
        path = args.get("path", "")
        if path:
            files_created.add(path)
            create_events.append((eid, path))

    # Also check for str_replace_editor "create" command
    if fn == "str_replace_editor" and args.get("command") == "create":
        path = args.get("path", "")
        if path:
            files_created.add(path)
            create_events.append((eid, path))

    # Track stuck detections
    error_id = extras.get("error_id", "")
    if "STUCK" in error_id:
        stuck_count += 1

    if action == "finish":
        print("FINISH at event %d" % eid)

print("Total events: %d" % len(event_files))
print("Tool calls: %d" % tool_calls)
print("Bash commands: %d" % bash_cmds)
print("Bash OK: %d" % bash_ok)
print("Bash errors: %d" % bash_err)
print("Stuck detections: %d" % stuck_count)
print("Files created: %d / 24" % len(files_created))
print()
print("Created files:")
for eid, path in create_events:
    dup = " (DUP)" if sum(1 for _, p in create_events if p == path) > 1 else ""
    print("  E%d: %s%s" % (eid, path, dup))

if bash_error_cmds:
    print("\nBash errors (%d):" % len(bash_error_cmds))
    for eid, code, cmd in bash_error_cmds[:15]:
        print("  E%d exit=%d: %s" % (eid, code, cmd[:120]))

# Show last 10 events summary
print("\nLast 10 events:")
for fname in event_files[-10:]:
    with open(os.path.join(events_dir, fname)) as f:
        e = json.load(f)
    eid = e.get("id", "?")
    action = e.get("action", "")
    source = e.get("source", "")
    obs = e.get("observation", "")
    tcm = e.get("tool_call_metadata", {})
    fn = tcm.get("function_name", "")
    args = e.get("args", {})
    detail = args.get("command", args.get("path", ""))
    if isinstance(detail, str):
        detail = detail[:80]
    print("  E%s [%s] %s/%s fn=%s | %s" % (eid, source, action, obs, fn, detail))
