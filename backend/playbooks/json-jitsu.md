---
name: json_jitsu
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /json
---

# JSON processing with jq

Slice, filter, and reshape JSON data on the command line.

## Field extraction

```bash
# Basic field access
jq '.message' file.json

# Nested
jq '.error.type' file.json

# All values of a field across an array
jq '.[].message' file.ndjson

# Multiple fields
jq '{msg: .message, lvl: .level}' file.ndjson
```

## Filtering

```bash
# By value
jq 'select(.level == "ERROR")' file.ndjson

# By nested field
jq 'select(.error.type == "invalid_request_error")' file.ndjson

# Multiple conditions
jq 'select(.level == "ERROR" and .message | test("context"))' file.ndjson

# First N matches
jq 'select(.level == "ERROR") | limit(5; .[])' file.ndjson
```

## Aggregation

```bash
# Count by field value
jq -r '.level' file.ndjson | sort | uniq -c | sort -rn

# Group and count (pure jq)
jq 'group_by(.level) | map({level: .[0].level, count: length})' file.ndjson

# Extract timing values
jq 'select(.message | test("done in")) | .message' file.ndjson -r | rg -o '\d+\.\d+'
```

## Transformations

```bash
# Pick fields, rename keys
jq '{timestamp: .asctime, msg: .message}' file.ndjson

# Format as table
jq -r '[.asctime, .level, .message] | @tsv' file.ndjson | column -t -s $'\t'

# Pretty-print single JSON
jq '.' file.json
```

## Handling log streams

```bash
# Parse JSONL logs
Get-Content logs/app.log | jq -c 'select(.level == "ERROR")' -R -s

# Tail with filter
tail -f logs/app.log | jq -c 'select(.level == "ERROR" or .level == "WARNING")' -R -s

# Convert timestamp to readable, filter window
jq 'select(.timestamp > "2026-05-25T19:10:00" and .timestamp < "2026-05-25T19:11:00")' logs.ndjson
```

## Example: error summary from JSONL

```bash
jq -r 'select(.level == "ERROR") | "[\(.asctime)] \(.message | split("\n")[0])"' app.ndjson | head -20
```
