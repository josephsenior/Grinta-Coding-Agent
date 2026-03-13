"""Analyze test run events in detail."""
import json
import os

events_dir = r"C:\Users\GIGABYTE\Desktop\Forge\storage\users\oss_user\conversations\2e275ff29ee84161ad1eeba432abf320\events"

# Show first 10 events structure
event_files = sorted(os.listdir(events_dir), key=lambda x: int(x.split(".")[0]))

print("=== First 10 events structure ===")
for fname in event_files[:10]:
    with open(os.path.join(events_dir, fname)) as f:
        e = json.load(f)
    eid = e.get("id", "?")
    action = e.get("action", "")
    source = e.get("source", "")
    obs = e.get("observation", "")
    args = e.get("args", {})
    tool = args.get("tool", "")
    path = args.get("path", "")
    cmd = args.get("command", "")
    print("E%s src=%s action=%s obs=%s tool=%s path=%s cmd=%s" % (
        eid, source, action, obs, tool, path[:60], cmd[:60]))
print()

files_created = set()
bash_cmds = 0
bash_ok = 0
bash_err = 0
tool_calls = 0
stuck_count = 0
bash_error_cmds = []

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

    # Track tool calls
    if source == "agent" and action in ("execute_bash", "str_replace_editor", "write"):
        tool_calls += 1

    # Track bash commands
    if action == "execute_bash" and source == "agent":
        bash_cmds += 1

    # Track command outputs (from environment)
    if obs in ("run", "command"):
        meta = extras.get("metadata", {})
        exit_code = meta.get("exit_code", -1)
        if exit_code == 0:
            bash_ok += 1
        elif exit_code > 0:
            bash_err += 1
            cmd_text = args.get("command", content[:200] if content else "")
            bash_error_cmds.append((eid, exit_code, cmd_text[:120]))

    # Track file creations
    if action == "str_replace_editor":
        cmd = args.get("command", "")
        path = args.get("path", "")
        if cmd == "create" and path:
            files_created.add(path)

    # Track stuck detections
    error_id = extras.get("error_id", "")
    if "STUCK" in error_id:
        stuck_count += 1

    # Track finish
    if action == "finish":
        print(f"FINISH at event {eid}")

print(f"Total events: {len(event_files)}")
print(f"Tool calls: {tool_calls}")
print(f"Bash commands sent: {bash_cmds}")
print(f"Bash OK: {bash_ok}")
print(f"Bash errors: {bash_err}")
print(f"Stuck detections: {stuck_count}")
print(f"Files created: {len(files_created)} / 24")
print()
print("Created files:")
for f in sorted(files_created):
    print(f"  {f}")

if bash_error_cmds:
    print(f"\nBash errors ({len(bash_error_cmds)}):")
    for eid, code, cmd in bash_error_cmds[:15]:
        print(f"  E{eid} exit={code}: {cmd}")
