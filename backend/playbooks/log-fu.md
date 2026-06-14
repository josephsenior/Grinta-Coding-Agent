---
name: log_fu
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /logs
  - /json
---

# Log and JSON analysis

Use when the user invokes **`/logs`** or **`/json`**. Find signal in noisy logs
and reshape JSON on the command line with `rg` and `jq`. Prefer `rg` for plain
text and `jq` for structured (JSON / NDJSON) data.

## Search plain-text logs (ripgrep)

```bash
# Time window (adjust the timestamp prefix to your format)
rg "2024-01-15T21:1[0-5]" logs/         # the 21:10-21:15 window

# Level filtering
rg '"level":\s*"ERROR"' logs/            # errors only
rg -v '"level":\s*"INFO"' logs/          # everything except INFO

# Correlate one request/session across files
rg "<request-id>" logs/ | rg "ERROR|WARN" | head -20
```

## Extract fields (jq)

```bash
jq '.message' file.json                  # single field
jq '.error.type' file.json               # nested field
jq '.[].message' file.ndjson             # field across an array
jq '{msg: .message, lvl: .level}' file.ndjson   # pick + rename
```

## Filter (jq)

```bash
jq 'select(.level == "ERROR")' file.ndjson
jq 'select(.error.type == "timeout")' file.ndjson
jq 'select(.level == "ERROR" and (.message | test("context")))' file.ndjson
```

## Aggregate and count

```bash
# Count by field value
jq -r '.level' file.ndjson | sort | uniq -c | sort -rn

# Group and count in pure jq
jq 'group_by(.level) | map({level: .[0].level, count: length})' file.ndjson

# Count occurrences of a pattern in text logs
rg "timed out" logs/ -o --no-filename | sort | uniq -c | sort -rn
```

## Timing analysis

```bash
# Pull durations out of a recurring log line
rg "completed in" logs/ -o --no-filename | rg -o '[0-9]+\.[0-9]+s'

# Slowest operations
rg "completed in " logs/ -o --no-filename | sort -t' ' -k3 -n | tail -5
```

## Format for humans

```bash
# NDJSON to an aligned table
jq -r '[.timestamp, .level, .message] | @tsv' file.ndjson | column -t -s $'\t'

# Pretty-print a single JSON document
jq '.' file.json
```

## Example: error summary from NDJSON

```bash
jq -r 'select(.level == "ERROR") | "[\(.timestamp)] \(.message | split("\n")[0])"' \
  app.ndjson | head -20
```
