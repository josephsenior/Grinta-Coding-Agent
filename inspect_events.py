"""Inspect detailed event data for a conversation."""
import json
import os
import sys

conv_id = sys.argv[1] if len(sys.argv) > 1 else "ab33100eb8f743db8da4b1a628efcac2"
start = int(sys.argv[2]) if len(sys.argv) > 2 else 7
end = int(sys.argv[3]) if len(sys.argv) > 3 else 60

conv_dir = os.path.join("storage", "users", "oss_user", "conversations", conv_id, "events")

for i in range(start, end + 1):
    path = os.path.join(conv_dir, f"{i}.json")
    if not os.path.exists(path):
        continue
    e = json.load(open(path))
    src = e.get("source", "?")
    act = e.get("action", "?")
    msg = e.get("message", "")
    content = e.get("content", "")
    tcm = e.get("tool_call_metadata") or {}
    fn = tcm.get("function_name", "")

    # Get tool call arguments from model response
    args_str = ""
    try:
        resp = tcm.get("model_response") or {}
        choices = resp.get("choices") or [{}]
        tcs = (choices[0].get("message") or {}).get("tool_calls") or []
        if tcs:
            raw = (tcs[0].get("function") or {}).get("arguments", "{}")
            args = json.loads(raw)
            args_str = str(args)[:150]
    except Exception:
        pass

    print(f"E{i:3d} [{fn:25s}] {act:8s} | {msg[:80]}")
    if args_str:
        print(f"       args: {args_str}")
    if content and content != msg:
        print(f"       content: {content[:120]}")
