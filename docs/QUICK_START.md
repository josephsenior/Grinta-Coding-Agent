# Quick Start

Install guide for all platforms (consumer, dev, Windows, WSL2, Linux, macOS).

**Paths:** only `<project>` is yours — the folder you want the agent to work in.  
Clone the repo into a folder named `Grinta` (e.g. `~/Grinta` on WSL).

Quote paths with spaces. First `grinta` runs setup — no `grinta init` required.

## Consumer vs dev

| | **Consumer** | **Dev (source)** |
| --- | --- | --- |
| Install | `pipx install grinta-ai` (PyPI) | `bash start_here.sh` or `.\START_HERE.ps1` once (bootstrap only) |
| Settings | `~/.grinta/settings.json` | `Grinta/settings.json` in your clone |
| Folders | `<project>` only | repo **and** `<project>` (often different) |
| Daily command | `cd "<project>"` → `grinta` | See **Dev daily use** |

`-p` — only when `<project>` is not your current directory.

---

## Dev daily use (after bootstrap)

From inside your clone (`cd ~/Grinta` or `cd Grinta`):

### A. `grinta` on PATH (recommended)

```bash
pipx install -e .              # once, from repo root
cd "<project>"
grinta
```

After big dependency changes: `pipx reinstall -e .` (from repo root).

### B. `uv run` (no global install)

`uv run --directory` changes cwd to the Grinta clone — pass your project explicitly:

```bash
cd "<project>"
uv run --directory /path/to/Grinta grinta -p "$(pwd)"
```

On WSL/Linux, Grinta also infers the project from your shell when you `cd` first (no `-p` needed in most cases).

### C. Open `<project>` without `cd`

```bash
uv run --directory /path/to/Grinta grinta -p "<project>"
```

---

## Windows (PowerShell)

Native Windows and WSL are **separate installs** (different binaries, different `~/.grinta/`).

### Consumer

```powershell
pipx install grinta-ai
cd "<project>"
grinta
```

### Dev — bootstrap once

```powershell
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git Grinta
cd Grinta
.\START_HERE.ps1
pipx install -e .    # optional; then daily `grinta` works from anywhere (way A)
```

Bootstrap does **not** open the TUI. Then:

### Dev — every day

```powershell
cd "<project>"
grinta
# or: uv run --directory C:\path\to\Grinta grinta
```

### Shell tool (native Windows only)

Default: Git Bash. For PowerShell in `settings.json`:

```json
"security": { "windows_shell": "powershell" }
```

---

## WSL (Ubuntu)

Install and run Grinta **inside Ubuntu**, not PowerShell. Windows `pipx` does not apply.

| Terminal | Install where |
| --- | --- |
| PowerShell / cmd / Git Bash | Windows (section above) |
| Ubuntu / WSL | Inside WSL |

**Dev layout:** clone to `~/Grinta`, not `/mnt/c`. `<project>` may be on `/mnt/c/...` (slower but OK).

**Path conversion:** `C:\foo\bar` → `/mnt/c/foo/bar` (quote if spaces).

**Preflight:** `grinta doctor` or `/health` in the TUI.

### Consumer

```bash
sudo apt install -y python3.12 python3.12-venv pipx
pipx ensurepath && source ~/.bashrc
pipx install grinta-ai
grinta doctor
cd "<project>"
grinta
```

### Dev — bootstrap once

```bash
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git ~/Grinta
cd ~/Grinta
bash start_here.sh
pipx install -e .    # optional
```

(Already have a copy on `/mnt/c`? `git clone /mnt/c/path/to/Grinta ~/Grinta` — then use the `~/` copy.)

Bootstrap does **not** open the TUI. Then:

### Dev — every day

```bash
cd "<project>"
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
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git Grinta
cd Grinta
bash start_here.sh
pipx install -e .
```

Bootstrap does **not** open the TUI. Then:

### Dev — every day

```bash
cd "<project>"
grinta
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
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git Grinta
cd Grinta
bash start_here.sh
pipx install -e .
```

Bootstrap does **not** open the TUI. Then:

### Dev — every day

```bash
cd "<project>"
grinta
```

---

## Optional

| Command | When |
| --- | --- |
| `grinta init` | Reconfigure without TUI |
| `grinta doctor` | Install / settings / WSL checks |
| `grinta -p "<project>"` | Open project without `cd` first |
| `pipx install "grinta-ai[rag]"` | Vector memory extra |

**Problems:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
