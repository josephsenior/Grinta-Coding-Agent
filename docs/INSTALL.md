# Installing Grinta

Command cheat sheet: [QUICK_START.md](QUICK_START.md) (consumer vs dev, all platforms).

## 1. `pipx` (recommended for most users)

Requires Python 3.12+ and `pipx`.

```bash
pipx install grinta-ai
cd /path/to/your/project
grinta
```

First interactive run runs the setup wizard automatically (provider + key). You do **not** need `grinta init` before the first `grinta`.

**Optional:** `grinta init` — reconfigure without the TUI; `grinta init --non-interactive` for CI. `grinta doctor` — troubleshoot install.

**Windows convenience (pipx):** [`START_HERE.ps1 -Pipx`](../START_HERE.ps1) or [`start_here.sh --pipx`](../start_here.sh) — probe local models and launch the TUI (setup runs on first launch if settings are missing).

Works on Windows, macOS, Linux. Settings: `~/.grinta/settings.json`.

**Windows + WSL:** separate install inside WSL — [WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md).

## 2. From source with `uv` (recommended for contributors)

**Prerequisites:** none for the start scripts — they install `uv` and Python 3.12 automatically when missing. Consumer `pipx` still needs Python 3.12+ and `pipx` on PATH.

**Minimal (first time):**

| Platform | Command |
| --- | --- |
| Windows | `.\START_HERE.ps1` |
| WSL / Linux / macOS | `bash start_here.sh` |

**On a project after setup:**

```bash
uv run --directory <Grinta-repo> python -m backend.cli.entry -p .
```

Manual bootstrap (equivalent to what `START_HERE` does):

```bash
uv python install 3.12
uv run python scripts/bootstrap_env.py dev-test
uv run python -m backend.cli.entry
```

First run runs setup automatically if no provider/key is configured. Optional: `uv run python -m backend.cli.entry init` to configure without launching the TUI.

Source checkouts use `<Grinta-repo>/settings.json`. Interactive TTY → Textual UI; piped stdin → non-interactive runner.

Optional local model discovery from source:

```bash
uv run python -m backend.inference.discover_models
uv run python -m backend.inference.discover_models status
```

## 3. Homebrew (macOS / Linuxbrew)

```bash
brew tap josephsenior/grinta https://github.com/josephsenior/Grinta-Coding-Agent
brew install grinta
grinta
```

The formula lives in [`packaging/homebrew/grinta.rb`](../packaging/homebrew/grinta.rb).

## 4. Scoop (Windows)

```powershell
scoop bucket add grinta https://github.com/josephsenior/Grinta-Coding-Agent
scoop install grinta
grinta
```

The manifest lives in [`packaging/scoop/grinta.json`](../packaging/scoop/grinta.json).

## 5. Docker (community / experimental)

```bash
docker pull ghcr.io/josephsenior/grinta:latest
docker run -it --rm -v "$PWD:/work" -w /work \
  -e LLM_API_KEY=${LLM_API_KEY} \
  ghcr.io/josephsenior/grinta:latest
```

A Docker Hub mirror is published as `josephsenior/grinta:latest`.

This repository does not currently ship a maintained `docker-compose.yml`. If you use
Docker, run the container image directly and treat this path as community-supported.

## Optional extras

```bash
pipx install "grinta-ai[rag]"      # chromadb + embeddings for semantic memory
pipx install "grinta-ai[browser]"  # browser-use for in-process Chromium automation
pipx install "grinta-ai[all]"       # both
```

When an extra is installed, matching tools appear automatically (config defaults are on). To disable after installing:

```json
"agent": {
  "Orchestrator": {
    "enable_vector_memory": false,
    "enable_hybrid_retrieval": false,
    "enable_browsing": false
  }
}
```

**RAG (`[rag]`):** `memory(recall)` and vector memory over long sessions.

**Browser (`[browser]`):** in-process `browser` tool. After install, run once: `uvx browser-use install`.

`web_search` / `web_fetch` are on the base install (no `[browser]` needed).

## After installation

- Run `grinta` from a project folder — setup runs automatically on first interactive launch.
- Optional: `grinta init` to reconfigure without the TUI; `grinta doctor` to troubleshoot.
- For manual settings, reference secrets as `${LLM_API_KEY}` and put the real value in `.env` next to `settings.json` or in your shell environment.
- Run `grinta --help` to see CLI flags and subcommands.
- Inside the terminal app, type `/help` for slash commands.
- Read [docs/SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) before pointing Grinta at untrusted code.

## Uninstall

- `pipx uninstall grinta-ai`
- `brew uninstall grinta`
- `scoop uninstall grinta`
- `docker rmi ghcr.io/josephsenior/grinta:latest`

## Common issues

See [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md).
