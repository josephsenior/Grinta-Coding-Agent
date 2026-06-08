import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "app.log"

# Noise substrings to skip (high-frequency, low-signal)
NOISE = (
    "on_event received StreamingChunkAction",
    "_dispatch_to_agent: poll #",
    "dispatching via run_or_schedule",
)

# Signal substrings to always show
SIGNAL = (
    "Setting agent",
    "reached end state",
    "AWAITING_USER_INPUT",
    "FINISHED",
    "STOPPED",
    "Watchdog",
    "watchdog",
    "stall",
    "circuit",
    "limit",
    "Pausing",
    "exhausted",
    "recovery round",
    "consecutive",
    "no tool call",
    "no-action",
    "timed out",
    "timeout",
    "Traceback",
    "astream error",
    "react_to_exception",
    "Error while running",
    "interrupt",
    "Ctrl",
    "cancel",
    "Closed",
    "close",
    "shutdown",
    "Saved converation stats",
    "Saved conversation stats",
)

def is_signal(msg, level):
    if level in ("ERROR", "CRITICAL"):
        return True
    for n in NOISE:
        if n in msg:
            return False
    for s in SIGNAL:
        if s in msg:
            return True
    return False

with open(path, encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        msg = str(rec.get("message", ""))
        level = str(rec.get("level", ""))
        if not is_signal(msg, level):
            continue
        ts = rec.get("asctime", "")
        sid = rec.get("session_id", "")
        sid_s = f" sid={sid}" if sid else ""
        # truncate long messages (tracebacks)
        short = msg.replace("\n", " | ")[:240]
        print(f"{i:6} {ts} [{level}]{sid_s} {short}")
