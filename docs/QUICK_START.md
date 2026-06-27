# Quick Start

## Consumer

Needs **Python 3.12+** and **pipx** (or Homebrew / Scoop — no manual Python).

```bash
pipx install grinta-ai
cd /path/to/project
grinta
```

First `grinta` runs setup. No `grinta init` required. Settings: `~/.grinta/settings.json`, secrets in `~/.grinta/.env`.

**Windows / WSL:** [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md) — WSL needs its own install.

**Other installs:** `brew install grinta` · `scoop install grinta` · Docker: `ghcr.io/josephsenior/grinta:latest`

**Extras:** `pipx install "grinta-ai[rag]"` · `"grinta-ai[browser]"` · `"grinta-ai[all]"`

**Uninstall:** `pipx uninstall grinta-ai`

## Dev (source)

No prerequisites — start scripts install `uv` + Python 3.12.

| Platform | Command |
| --- | --- |
| Windows | `.\START_HERE.ps1` |
| Unix / WSL | `bash start_here.sh` |

On a project: `uv run --directory <Grinta-repo> python -m backend.cli.entry -p .`

Settings: `<Grinta-repo>/settings.json`

## Optional

| Command | When |
| --- | --- |
| `grinta init` | Reconfigure without TUI; `--non-interactive` for CI |
| `grinta doctor` | Install / settings / `rg` checks |
| `grinta -p <path>` | Open project without `cd` |

## Problems

| Problem | Fix |
| --- | --- |
| `grinta` not found in WSL | Install inside Ubuntu — [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md) |
| `uv` not found (dev) | Run `START_HERE.ps1` / `start_here.sh` |
| WSL path | `C:\foo` → `"/mnt/c/foo"` |
| More | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

Config reference: [SETTINGS.md](SETTINGS.md) · modes & slash commands: [USER_GUIDE.md](USER_GUIDE.md)
