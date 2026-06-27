# Quick Start

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

---

## WSL (Ubuntu)

Windows `pipx` does not apply — install **inside Ubuntu** (Linux Grinta, not PowerShell).  
`C:\foo\bar` → `/mnt/c/foo/bar`

**Official supported layout:** repo on `~/Grinta`, project may be on `/mnt/c`. See [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md).

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
# Clone to Linux home (not /mnt/c)
git clone "<wsl-grinta-repo-source>" ~/Grinta
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
| `grinta doctor` | Install / settings checks |
| `grinta -p <path>` | Open project without `cd` first |
| `pipx install "grinta-ai[rag]"` | Vector memory extra |

**Windows / WSL:** [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md) · **Problems:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
