---
name: shell
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /shell
  - /bash
---

# Shell and CLI execution

Use this when writing shell scripts (`.sh`, `.ps1`) or running terminal commands for the user.

## Principles

1. **Non-Interactive First**: Never run commands that pop up interactive prompts (e.g. `npm init` without `-y`, or `apt install` without `-y`). Always supply necessary flags to force non-interactive execution.
2. **Robustness**: 
   - Bash: Always use `set -euo pipefail` in scripts so they fail fast on errors or unbound variables.
   - PowerShell: Use `$ErrorActionPreference = 'Stop'`.
3. **Data Parsing**: Output pure JSON or strict line-delimited formats when chaining tools. Use `jq` to reliably slice data instead of fragile `awk/sed/grep` combinations if structures are nested.
4. **Validation**: Check exit codes. If a command fails, read the `stderr`, form a hypothesis, and fix the command instead of endlessly retrying the same flawed string.

## Bash Example

```bash
#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-./default_dir}"

if [[ ! -d "$TARGET_DIR" ]]; then
  echo "Error: Directory $TARGET_DIR does not exist." >&2
  exit 1
fi
```

## Anti-Patterns

- ❌ `rm -rf /` or untested glob deletions (`rm -rf ./*`). Use focused, specific deletion paths.
- ❌ Guessing paths. Always verify the current working directory (`pwd`) or list the directory contents before executing a script that depends on relative paths.
