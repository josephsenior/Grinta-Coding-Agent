# Windows and WSL

**Windows install ≠ WSL install.** Commands: [QUICK_START.md](QUICK_START.md).

## Rules

| Terminal | Install where |
| --- | --- |
| PowerShell / cmd / Git Bash | Windows |
| Ubuntu / WSL | Inside WSL (separate `pipx` or `uv`) |

## WSL path conversion

| Windows | WSL |
| --- | --- |
| `D:\code\my-app` | `/mnt/d/code/my-app` |
| `C:\path with spaces\app` | `"/mnt/c/path with spaces/app"` |

Rule: `/mnt/<drive>/` + path with `\` → `/`. Quote if spaces.

Dev: `--directory` = `<wsl-grinta-repo>` · `-p` = `<wsl-project>` only if you skip `cd`. Daily: `pipx install -e "<repo>"` then `cd "<project>"` && `grinta` — [QUICK_START.md](QUICK_START.md#dev-daily-use-after-bootstrap).

## Native Windows shell tool

Default: `execute_bash` (Git Bash). For PowerShell:

```json
"security": { "windows_shell": "powershell" }
```

Settings: Windows consumer `~/.grinta/` (Windows home) · WSL consumer `~/.grinta/` (Linux home) — not shared.
