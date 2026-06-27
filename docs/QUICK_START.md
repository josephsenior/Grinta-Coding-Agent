# Quick Start

Replace `<Grinta-repo>` with your clone path (e.g. `~/Grinta`, `C:\Users\you\Grinta`).

## Consumer mode (use the app)

**Prerequisites:** Python 3.12+ and `pipx`.

**Minimal path — two commands:**

```bash
pipx install grinta-ai
cd /path/to/your/project
grinta
```

On **first** interactive run, `grinta` runs the setup wizard automatically (provider + API key, or local Ollama). You do **not** need `grinta init` first.

**Settings:** `~/.grinta/settings.json` (pipx install) · secrets in `~/.grinta/.env`

**Windows / WSL:** install `pipx` in the same environment you run from. WSL is a separate install — see [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md).

---

## Dev mode (source checkout)

**Prerequisites:** none — the start scripts install `uv` and Python 3.12 automatically if missing.

**Minimal path — one command (first time):**

| Platform | Command |
| --- | --- |
| Windows (PowerShell) | `.\START_HERE.ps1` |
| WSL / Linux / macOS | `bash start_here.sh` |

That syncs deps, runs setup if needed, and launches Grinta.

**Run on a project after setup:**

```bash
cd /path/to/your/project
uv run --directory <Grinta-repo> python -m backend.cli.entry -p .
```

**Settings:** `<Grinta-repo>/settings.json` · **Logs:** `<Grinta-repo>/logs/`

---

## Optional commands (when you actually need them)

| Command | Use when |
| --- | --- |
| `grinta init` | Change provider/model/key **without** opening the TUI; or `grinta init --non-interactive` for scripts/CI |
| `grinta doctor` | Something failed — check settings, model key, `rg`, optional tools |
| `grinta -p /path/to/project` | Open a project without `cd` first |
| `pipx install -e <Grinta-repo>` | Dev only: type `grinta` from any folder while running local code |
| `uv run --directory <Grinta-repo> python -m backend.cli.entry init --force` | Dev only: reset repo `settings.json` |
| `uv run pytest backend/tests/unit/ -q` | Dev only: run unit tests |

**You can skip** `grinta init` and `grinta doctor` on a normal first run if `grinta` works.

---

## Other install paths

Homebrew, Scoop, Docker: [INSTALL.md](INSTALL.md)

## Common issues

| Problem | Fix |
| --- | --- |
| `uv` not found (dev) | Run `START_HERE.ps1` / `start_here.sh` — they auto-install `uv` and Python 3.12 |
| `grinta` not found (dev) | Use `uv run --directory <Grinta-repo> ...` or optional `pipx install -e` |
| `grinta` not found in **WSL** | `pipx install grinta-ai` **inside** Ubuntu — [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md) |
| `cd` to a Windows folder in WSL | `C:\Users\you\foo` → `"/mnt/c/Users/you/foo"` |
| Non-interactive / piped run, no config | `grinta init --non-interactive` with `LLM_API_KEY` set |
| More help | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
