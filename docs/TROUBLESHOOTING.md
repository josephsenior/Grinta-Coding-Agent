# Troubleshooting Guide

This guide targets the current Grinta runtime:

- terminal-first local execution
- Textual TUI for interactive TTY runs, non-interactive runner for piped stdin
- installed `~/.grinta/settings.json` or source-checkout `settings.json` for default local config

## Table of Contents

1. Installation Issues
2. Startup Issues
3. LLM Provider Issues
4. Runtime and Policy Issues
5. Windows-Specific Issues
6. Diagnostics

---

## Installation Issues

### Consumer: `pipx` or `grinta` not found

Symptom:

- `pipx: command not found` or `grinta: command not found` after install

Fix:

1. Install **Python 3.12+** and **pipx** (see [INSTALL.md](INSTALL.md)).
2. Run `pipx ensurepath` and open a new terminal.
3. `pipx install grinta-ai` then `grinta`.

Alternatives without manual Python/pipx: Homebrew, Scoop, or Docker — [INSTALL.md](INSTALL.md).

### Dev: `uv` not found

Symptom:

- `uv` is not recognized (source checkout)

Fix:

Run the start script — it installs `uv` and Python 3.12 automatically:

```powershell
.\START_HERE.ps1
```

```bash
bash start_here.sh
```

Or install manually:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal, then verify: `uv --version`

### Python version mismatch (dev / source)

Symptom:

- startup says Python 3.12+ is required (source checkout)

Fix:

```bash
uv python install 3.12
uv run python --version
```

Or re-run `START_HERE.ps1` / `start_here.sh`.

### Dependency resolution failed

Fix:

```bash
uv lock
uv sync
```

---

## Startup Issues

### CLI does not start

Use the canonical command:

```bash
uv run python -m backend.cli.entry
```

For installed CLI runs, use:

```bash
grinta
```

If startup fails, check:

1. `settings.json` exists at the active settings root (`~/.grinta` for installed runs, the repo root for source checkouts, or `APP_ROOT` if set).
2. `llm_model` and `llm_api_key` are set correctly.
3. Current directory is the project root for source runs, or set `APP_ROOT` intentionally.

### Textual UI does not appear

Grinta only starts the full Textual app when stdin is an interactive TTY. If you
pipe input, redirect stdin, or run from a tool that does not expose a real TTY,
Grinta uses the non-interactive runner.

Useful checks:

```bash
uv run python -m backend.cli.entry --help
uv run python -m backend.cli.entry --no-splash
uv run python -m backend.cli.entry --accessible
```

Use `--minimal` for a reduced HUD and `--theme <preset>` to test a different
theme.

### Invalid configuration

Symptom:

- validation errors on launch

Fix:

1. Regenerate settings file from template.
2. Keep JSON valid (no trailing commas).
3. Start from minimal keys first.

```bash
uv run python -m backend.cli.entry init
```

Minimal known-good example:

```json
{
  "llm_provider": "openai",
  "llm_model": "openai/gpt-5.1",
  "llm_api_key": "${LLM_API_KEY}",
  "llm_base_url": ""
}
```

---

## LLM Provider Issues

### 401 — Invalid API key

**Symptom:** Authentication errors on startup or during calls.

**Fix:** Verify your key matches the provider and model prefix:
- OpenAI key with `openai/...` models
- Anthropic key with `anthropic/...` models
- Google key with `google/...` models

See [USER_GUIDE.md](USER_GUIDE.md#llm-provider-setup) for configuration examples.

### 402 — Insufficient balance

**Symptom:** Provider reports billing/payment issues.

**Fix:** This is provider-side. Verify account credits and organization/project selection in your provider dashboard.

### Model not found

**Symptom:** Model doesn't exist or isn't available.

**Fix:** Use provider-qualified model IDs:
- `openai/gpt-5.1`
- `anthropic/claude-sonnet-4.6`
- `google/gemini-2.5-pro`
- `ollama/llama3.2`

From a source checkout, inspect local providers with:

```bash
uv run python -m backend.inference.discover_models
uv run python -m backend.inference.discover_models status
```

### Ollama unavailable

**Symptom:** Connection refused or timeout when using local models.

**Fix:** Start Ollama first:

```bash
ollama serve
ollama pull llama3.2
```

---

## Runtime and Policy Issues

### Agent appears stuck

Grinta includes stuck detection and circuit breaker controls. If progress stalls:

1. Stop the run.
2. Re-issue a more explicit task.
3. Reduce scope to one concrete deliverable.
4. Try a stronger model.

### Permission errors on file edits

Check workspace permissions and file locks.

On Windows, close editors that may hold locks.

### Safety policy blocks command

If strict local policy is active, risky commands may be blocked. This is expected behavior.

---

## Windows-Specific Issues

Full guide (Git Bash vs PowerShell vs WSL, path mapping, separate installs): **[WINDOWS_AND_WSL.md](WINDOWS_AND_WSL.md)**.

### `grinta: command not found` in WSL / Ubuntu

Symptom:

- You opened an Ubuntu/WSL terminal, `cd`'d to a folder, ran `grinta`, and the shell says command not found.

Cause:

- WSL is Linux. A Windows `pipx install` does not install into WSL.

Fix (inside Ubuntu):

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv pipx
pipx ensurepath && source ~/.bashrc
pipx install grinta-ai
grinta
```

First interactive run runs setup automatically.

### `cd` to a Windows folder in WSL

`C:\Users\you\Desktop\New folder` becomes:

```bash
cd "/mnt/c/Users/you/Desktop/New folder"
```

### Agent uses PowerShell instead of bash on Windows

Set in `settings.json`:

```json
"security": { "windows_shell": "bash" }
```

See [SETTINGS.md](SETTINGS.md).

### Long path problems

Enable long paths (admin PowerShell):

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

### Shell behavior differences

Native Windows: use `.\START_HERE.ps1` (PowerShell) or Git Bash with `grinta` after a Windows install.

WSL: use `bash start_here.sh` after installing **inside** the distro — not the Windows install.

---

## Diagnostics

### Standalone environment check

Run outside the TUI for a full install report (settings schema, LLM key resolution, `git`, `rg`, optional debugpy):

```bash
grinta doctor
```

Use `grinta doctor --verbose` to include the editing-stack probe. Exit code `1` means at least one **critical** check failed.

### In-session quick check

Inside the TUI or legacy REPL:

```text
/health
```

`/health` uses the same check registry as `grinta doctor` but only runs the fast subset (debugpy, git, ripgrep, model). For settings-file or schema problems, prefer `grinta doctor`.

### Contributor checks

```bash
python --version
uv --version
git --version
uv run python -m backend.cli.entry --help
```

Quick local tests:

```bash
uv run pytest backend/tests/unit/ --tb=short -q
```

That matches the required CI unit gates. A bare `uv run pytest` from the repo root runs the full **`backend/tests`** tree per [`pytest.ini`](../pytest.ini) (much slower).

---

## Need more help?

If the issue persists:

1. Check [SUPPORT_MATRIX.md](SUPPORT_MATRIX.md) for version/platform compatibility
2. Review recent changes in [CHANGELOG.md](../CHANGELOG.md)
3. Open an issue with:
   - Repro steps
   - Exact command used
   - Full error output
   - OS and Python version
   - Redacted `settings.json` fields (`llm_provider`, `llm_model`, base_url presence)
