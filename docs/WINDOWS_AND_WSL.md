# Windows and WSL

**Windows install ≠ WSL install.** Commands: [QUICK_START.md](QUICK_START.md).

## Official WSL2 tier

WSL2 is **supported** when you run Grinta as a **Linux app inside Ubuntu** (not Windows `pipx` in PowerShell).

| Component | Where | Notes |
| --- | --- | --- |
| Grinta install | Inside WSL Ubuntu (`pipx` or `uv`) | Separate from native Windows install |
| Grinta repo + venv (dev) | Linux home, e.g. `~/Grinta` | **Required** — do not keep repo on `/mnt/c` |
| Your project | `~/project` or `/mnt/c/Users/...` | Project on Windows drive is **OK** (slower I/O) |
| Settings | `~/.grinta/` in Ubuntu | Not shared with `C:\Users\...\.grinta\` |

```text
Windows
  └── WSL Ubuntu          ← Linux environment (install Grinta here)
        ├── ~/Grinta      ← repo + venv (fast)
        └── /mnt/c/...    ← your project workspace (supported, slower)
```

### Golden path (dev)

```bash
# One-time: clone to Linux disk
git clone /mnt/c/Users/you/Desktop/Grinta ~/Grinta
cd ~/Grinta && bash start_here.sh

# Daily: agent on your Windows project folder
cd "/mnt/c/Users/you/Desktop/New folder"
uv run --directory ~/Grinta grinta
```

### Golden path (consumer)

```bash
sudo apt install -y python3.12 python3.12-venv pipx
pipx ensurepath && source ~/.bashrc
pipx install grinta-ai
cd "/mnt/c/Users/you/Desktop/New folder"
grinta
```

### Preflight

```bash
grinta doctor          # full report including WSL layout checks
```

In the TUI: `/health` (fast subset). Fix any `wsl_layout` failures before large agent tasks.

### When to use native Windows instead

If you do not need Linux-only tooling, **native Windows** (`pipx install grinta-ai` in PowerShell) is simpler and avoids drvfs I/O. See [QUICK_START.md](QUICK_START.md).

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

## Performance notes (WSL2 only)

- **Repo on `/mnt/c`**: slow checkpoints, MCP stdio, pytest — move repo to `~/Grinta`
- **Project on `/mnt/c`**: file tools work but are slower than `~/project`; expected
- **tmux sockets**: auto-placed under `/tmp/grinta-tmux` on WSL

## Native Windows shell tool

Default: `execute_bash` (Git Bash). For PowerShell:

```json
"security": { "windows_shell": "powershell" }
```

Settings: Windows consumer `~/.grinta/` (Windows home) · WSL consumer `~/.grinta/` (Linux home) — not shared.
