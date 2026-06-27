# Quick Start

Single install guide for all platforms (consumer, dev, Windows, WSL2, Linux, macOS).

| Placeholder | Meaning |
| --- | --- |
| `<Grinta-repo>` | Grinta source checkout (`pyproject.toml` lives here) |
| `<project>` | Folder the agent should work in (your code) |

Quote paths with spaces. First `grinta` runs setup — no `grinta init` required.

## Consumer vs dev

| | **Consumer** | **Dev (source)** |
| --- | --- | --- |
| Install | `pipx install grinta-ai` (PyPI) | Bootstrap `<Grinta-repo>` once (below) |
| Settings | `~/.grinta/settings.json` | `<Grinta-repo>/settings.json` |
| Folders | `<project>` only | `<Grinta-repo>` **and** `<project>` (often different) |
| Daily command | `cd "<project>"` → `grinta` | See **Dev daily use** |

`-p <path>` — only when the project is **not** your current directory. If you `cd` into `<project>` first, plain `grinta` uses the cwd.

---

## Dev daily use (after bootstrap)

Pick **one** way to run local code on `<project>`:

### A. `grinta` on PATH (recommended for daily dev)

```bash
pipx install -e "<Grinta-repo>"    # once per machine
cd "<project>"
grinta
```

Re-run after big dependency changes: `pipx reinstall -e "<Grinta-repo>"`.

### B. `uv run` (no global `grinta` install)

```bash
cd "<project>"
uv run --directory "<Grinta-repo>" grinta
```

### C. Open a project without `cd`

```bash
uv run --directory "<Grinta-repo>" grinta -p "<project>"
```

Long form (same as B/C): `uv run --directory "<Grinta-repo>" python -m backend.cli.entry` (add `-p "<project>"` only for C).

---

## Windows (PowerShell)

Native Windows and WSL are **separate installs** (different `grinta` binaries, different `~/.grinta/`).

### Consumer

```powershell
pipx install grinta-ai
cd "<project>"
grinta
```

### Dev — bootstrap once

```powershell
cd "<Grinta-repo>"
.\START_HERE.ps1
pipx install -e "<Grinta-repo>"    # optional; enables daily `grinta` (way A)
```

### Dev — every day

```powershell
cd "<project>"
grinta
# or: uv run --directory "<Grinta-repo>" grinta
```

### Shell tool (native Windows only)

Default: `execute_bash` (Git Bash). For PowerShell in `settings.json`:

```json
"security": { "windows_shell": "powershell" }
```

---

## WSL (Ubuntu)

**Windows `pipx` does not apply** — install and run Grinta **inside Ubuntu** (Linux app), not PowerShell.

| Terminal | Install where |
| --- | --- |
| PowerShell / cmd / Git Bash | Windows (section above) |
| Ubuntu / WSL | Inside WSL (`pipx` or `uv`) |

### Official WSL2 layout

| Component | Where | Notes |
| --- | --- | --- |
| Grinta install | Inside WSL Ubuntu | Separate from native Windows |
| Grinta repo + venv (dev) | Linux home, e.g. `~/Grinta` | **Required** — not on `/mnt/c` |
| Your project | `~/project` or `/mnt/c/Users/...` | On Windows drive is OK (slower I/O) |
| Settings | `~/.grinta/` in Ubuntu | Not shared with `C:\Users\...\.grinta\` |

```text
Windows
  └── WSL Ubuntu
        ├── ~/Grinta      ← repo + venv (fast)
        └── /mnt/c/...    ← project workspace (supported, slower)
```

**Path conversion:** `C:\foo\bar` → `/mnt/c/foo/bar` · `D:\code\app` → `/mnt/d/code/app` (quote if spaces).

**Performance:** repo on `/mnt/c` is slow (checkpoints, MCP, pytest) — use `~/Grinta`. Project on `/mnt/c` is slower but supported. tmux sockets use `/tmp/grinta-tmux` on WSL.

**Preflight:** `grinta doctor` (full) or `/health` in the TUI (fast). Fix `wsl_layout` warnings before large tasks.

**Prefer native Windows?** If you do not need Linux-only tooling, PowerShell + `pipx install grinta-ai` is simpler — see **Windows** above.

### Consumer

```bash
sudo apt install -y python3.12 python3.12-venv pipx
pipx ensurepath && source ~/.bashrc
pipx install grinta-ai
grinta doctor
cd "/mnt/c/Users/you/Desktop/your-project"
grinta
```

### Dev — bootstrap once

```bash
git clone /mnt/c/Users/you/Desktop/Grinta ~/Grinta   # Linux home, not /mnt/c
cd ~/Grinta
bash start_here.sh
pipx install -e ~/Grinta    # optional; enables daily `grinta` (way A)
```

### Dev — every day

```bash
cd "/mnt/c/Users/you/Desktop/your-project"
grinta
# or: uv run --directory ~/Grinta grinta
```

---

## Linux

### Consumer

```bash
pipx install grinta-ai
cd "<project>"
grinta
```

### Dev — bootstrap once

```bash
cd "<Grinta-repo>"
bash start_here.sh
pipx install -e "<Grinta-repo>"
```

### Dev — every day

```bash
cd "<project>"
grinta
# or: uv run --directory "<Grinta-repo>" grinta
```

---

## macOS

### Consumer (pipx)

```bash
pipx install grinta-ai
cd "<project>"
grinta
```

### Consumer (Homebrew)

```bash
brew tap josephsenior/grinta https://github.com/josephsenior/Grinta-Coding-Agent
brew install grinta
cd "<project>"
grinta
```

### Dev — bootstrap once

```bash
cd "<Grinta-repo>"
bash start_here.sh
pipx install -e "<Grinta-repo>"
```

### Dev — every day

```bash
cd "<project>"
grinta
# or: uv run --directory "<Grinta-repo>" grinta
```

---

## Optional

| Command | When |
| --- | --- |
| `grinta init` | Reconfigure without TUI; `--non-interactive` for CI |
| `grinta doctor` | Install / settings / WSL layout checks |
| `grinta -p <path>` | Open project without `cd` first |
| `pipx install "grinta-ai[rag]"` | Vector memory extra |

**Problems:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
