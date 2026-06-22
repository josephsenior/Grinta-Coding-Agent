# Installing Grinta

Grinta is a local-first terminal coding agent. Pick the installation path that matches how you work.

## 1. `pipx` (recommended for most users)

Requires Python 3.12+ and `pipx`.

```bash
pipx install grinta-ai
grinta init           # First-run wizard: pick provider, paste key
grinta                # Start the terminal app
```

**Windows convenience (pipx):** after `pipx install grinta-ai`, run
[`START_HERE.ps1`](START_HERE.ps1) with `-Pipx` from a source checkout (or run
[`scripts/launch/start_here_pipx.ps1`](scripts/launch/start_here_pipx.ps1)
directly) to probe local model servers, run `grinta init` when
`~/.grinta/settings.json` is missing, and launch the TUI. Unix/macOS pipx users:
[`start_here.sh --pipx`](start_here.sh).

Works on Windows, macOS, Linux. Requires Python 3.12+. Installed runs store settings at `~/.grinta/settings.json` and runtime state under `~/.grinta/workspaces/<id>/storage`.

## 2. From source with `uv` (recommended for contributors)

Requires Python 3.12+ and `uv`.

```bash
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git
cd Grinta-Coding-Agent
python scripts/bootstrap_env.py dev-test
uv run python -m backend.cli.entry init
uv run python -m backend.cli.entry
```

Source checkouts use the repository `settings.json` by default so contributors can keep project-local development config.
Interactive TTY sessions launch the Textual UI; piped stdin uses the non-interactive runner.

Optional local model discovery from source:

```bash
uv run python -m backend.inference.discover_models
uv run python -m backend.inference.discover_models status
```

## 3. Homebrew (macOS / Linuxbrew)

```bash
brew tap josephsenior/grinta https://github.com/josephsenior/Grinta-Coding-Agent
brew install grinta
grinta init
```

The formula lives in [`packaging/homebrew/grinta.rb`](../packaging/homebrew/grinta.rb).

## 4. Scoop (Windows)

```powershell
scoop bucket add grinta https://github.com/josephsenior/Grinta-Coding-Agent
scoop install grinta
grinta init
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

## After installation

- Run `grinta init` to configure your LLM provider interactively.
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
