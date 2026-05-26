---
name: log_fu
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /logs
---

# Log analysis

Find signal in noisy logs with grep, timing analysis, and rate tracking.

## Search patterns

```bash
# Time window
rg "2026-05-25T21:1[0-5]" logs/          # 10-15 minute window
rg "2026-05-25T21:10:0[0-9]" logs/       # first 10 seconds of minute 10

# Level filtering
rg '"level": "ERROR"' logs/              # errors only
rg '"level": "WARNING"' logs/            # warnings only

# Exclude noise
rg -v '"level": "INFO"' logs/ | rg '"level"'   # non-INFO entries
```

## Timing analysis

```bash
# Extract timing between two log lines
rg "async_execute done in" logs/ -o --no-filename | rg -o '\d+\.\d+s'

# Find slowest operations
rg "done in " logs/ -o --no-filename | sort -t' ' -k3 -n | tail -5

# Trace a single session
rg "df4ef495" logs/ | rg "ERROR|WARNING" | head -20
```

## Rate and frequency

```bash
# Count errors per minute
rg '"level": "ERROR"' logs/ -c --no-filename

# Count event types
rg "on_event received" logs/ -o --no-filename | sort | uniq -c | sort -rn

# Poll frequency of a session
rg "poll #" logs/ --no-filename -o | sed 's/poll #//' | awk 'NR>1{print $1-p}'
```

## Pattern cheat sheet

| Pattern | What it finds |
|---------|--------------|
| `"cleared in-memory file store"` | Event persistence milestones |
| `"Memory pressure WARNING"` | RSS approaching limit |
| `"Agent-survivable error"` | Non-fatal error, agent kept running |
| `"context window exceeds"` | Provider context overflow |
| `"OrchestratorExecutor.async_execute done in"` | LLM step duration |

## Example: find error bursts

```bash
grep -n '"level": "ERROR"' logs/app.log | cut -d: -f1 | \
  awk 'NR>1{print $1-prev}{prev=$1}' | sort -rn | head -5
```
