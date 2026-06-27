# Quick Start

Replace placeholders with **your** paths:

| Placeholder | Meaning |
| --- | --- |
| `<Grinta-repo>` | Grinta source checkout (contains `pyproject.toml`) |
| `<project>` | Folder you want the agent to work in |

**Dev mode uses both.** Consumer mode only needs `<project>`. Quote paths that contain spaces.

First `grinta` runs setup. No `grinta init` required.

---

## Windows (PowerShell)

### Consumer

```powershell
pipx install grinta-ai
cd "<project>"
grinta
```

### Dev

```powershell
cd "<Grinta-repo>"
.\START_HERE.ps1

uv run --directory "<Grinta-repo>" python -m backend.cli.entry -p "<project>"
```

Settings: `<Grinta-repo>\settings.json`

---

## WSL (Ubuntu)

Install inside WSL — Windows `pipx` does not apply.

**Windows path → WSL:** `C:\foo\bar` → `/mnt/c/foo/bar` (lowercase drive letter, forward slashes, quote spaces).

### Consumer

```bash
sudo apt install -y python3.12 python3.12-venv pipx
pipx ensurepath && source ~/.bashrc
pipx install grinta-ai
cd "<wsl-project>"
grinta
```

(`<wsl-project>` = WSL form of `<project>`, e.g. `/mnt/c/Users/Alice/code/my-app`)

Settings: `~/.grinta/settings.json`

### Dev

```bash
cd "<wsl-grinta-repo>"
bash start_here.sh

uv run --directory "<wsl-grinta-repo>" python -m backend.cli.entry -p "<wsl-project>"
```

Settings: `<wsl-grinta-repo>/settings.json`

---

## Linux

### Consumer

```bash
pipx install grinta-ai
cd "<project>"
grinta
```

### Dev

```bash
cd "<Grinta-repo>"
bash start_here.sh

uv run --directory "<Grinta-repo>" python -m backend.cli.entry -p "<project>"
```

Settings: `<Grinta-repo>/settings.json`

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

### Dev

```bash
cd "<Grinta-repo>"
bash start_here.sh

uv run --directory "<Grinta-repo>" python -m backend.cli.entry -p "<project>"
```

Settings: `<Grinta-repo>/settings.json`

---

## Optional

| Command | When |
| --- | --- |
| `grinta init` | Reconfigure without TUI; `--non-interactive` for CI |
| `grinta doctor` | Install / settings checks |
| `grinta -p <path>` | Consumer: open project without `cd` |

**Extras:** `pipx install "grinta-ai[rag]"` · `"grinta-ai[browser]"` · `"grinta-ai[all]"`

**Windows / WSL pitfalls:** [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md) · **Problems:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
