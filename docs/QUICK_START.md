# Quick Start

Prerequisites: Python 3.12+ and `uv` (dev) or `pipx` (consumer).

Replace `<Grinta-repo>` with your clone path (e.g. `~/Grinta`, `C:\Users\you\Grinta`).

## Consumer mode (Windows · WSL/Linux · macOS)

Installed app — same commands on all platforms.

| Step | Command |
|------|---------|
| Install once | `pipx install grinta-ai` |
| Setup once | `grinta init` |
| Run from project folder | `cd /path/to/project` → `grinta` |
| Explicit project path | `grinta -p /path/to/project` |
| Check setup | `grinta doctor` |

Settings: `~/.grinta/settings.json`

## Dev mode (Windows · WSL/Linux · macOS)

Source checkout — contributors and local hacking.

| Step | Windows (PowerShell) | WSL / Linux / macOS |
|------|----------------------|---------------------|
| Setup once | `.\START_HERE.ps1` | `bash start_here.sh` |
| Run from project | `cd C:\path\to\project` → `uv run --directory <Grinta-repo> python -m backend.cli.entry -p .` | `cd /path/to/project` → `uv run --directory <Grinta-repo> python -m backend.cli.entry -p .` |
| Re-run init | `uv run --directory <Grinta-repo> python -m backend.cli.entry init --force` | same |
| Unit tests | `cd <Grinta-repo>` → `uv run pytest backend/tests/unit/ -q` | same |

Settings: `<Grinta-repo>/settings.json`  
Logs: `<Grinta-repo>/logs/` ([logs/README.md](../logs/README.md))

## Dev shortcut — type `grinta` anywhere

```bash
pipx install -e <Grinta-repo>
```

Then use **consumer** commands from any project folder while running local code.

## Other install paths

Homebrew, Scoop, Docker: [INSTALL.md](INSTALL.md)

## Common issues

| Problem | Fix |
|---------|-----|
| `uv` not found | https://docs.astral.sh/uv/ |
| `grinta` not found (dev) | Use full `uv run --directory <Grinta-repo> ...` or `pipx install -e` |
| Local models | Start Ollama/LM Studio/vLLM; pick provider in `grinta init` |
| More help | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
