# Installing Grinta

Grinta is a local-first CLI coding agent. Three installation paths — pick whichever you already use.

## 1. `pipx` (recommended for most users)
```bash
pipx install grinta-ai
grinta init           # First-run wizard: pick provider, paste key
grinta                # Start the REPL
```
Works on Windows, macOS, Linux. Requires Python 3.12+.

## 2. From source with `uv` (recommended for contributors)
```bash
git clone https://github.com/josephsenior/Grinta-Coding-Agent.git
cd Grinta-Coding-Agent
uv sync
uv run python -m backend.cli.entry init
uv run python -m backend.cli.entry
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

## 5. Docker
```bash
docker pull ghcr.io/josephsenior/grinta:latest
docker run -it --rm -v "$PWD:/work" -w /work \
  -e LLM_API_KEY=$LLM_API_KEY \
  ghcr.io/josephsenior/grinta:latest
```
A Docker Hub mirror is published as `josephsenior/grinta:latest`.

## After installation
- Run `grinta init` to configure your LLM provider interactively.
- Run `grinta --help` to see CLI flags and subcommands.
- Inside the REPL, type `/help` for slash commands.
- Read [docs/SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md) before pointing Grinta at untrusted code.

## Uninstall
- `pipx uninstall grinta-ai`
- `brew uninstall grinta`
- `scoop uninstall grinta`
- `docker rmi ghcr.io/josephsenior/grinta:latest`

## Common issues
See [docs/TROUBLESHOOTING.md](TROUBLESHOOTING.md).
