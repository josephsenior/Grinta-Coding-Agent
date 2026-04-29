# Troubleshooting Guide

This guide targets the current Grinta runtime:

- CLI-first local execution
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

### uv not found

Symptom:

- `uv` is not recognized

Fix:

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart your terminal, then verify:

```bash
uv --version
```

### Python version mismatch

Symptom:

- startup says Python 3.12+ is required

Fix:

```bash
python --version
```

Install Python 3.12+ and re-run `uv sync`.

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
  "llm_model": "openai/gpt-4o-mini",
  "llm_api_key": "${LLM_API_KEY}",
  "llm_base_url": ""
}
```

---

## LLM Provider Issues

### 401 / invalid API key

Check that your key matches your provider and model prefix.

Examples:

- OpenAI key with `openai/...`
- Anthropic key with `anthropic/...`
- Google key with `google/...`

### 402 / insufficient balance

This is provider-side billing. Verify account credits and organization/project selection.

### Model not found

Use a provider-qualified model id when possible:

- `openai/gpt-4o-mini`
- `anthropic/claude-sonnet-4-20250514`
- `google/gemini-2.5-pro`
- `ollama/llama3.2`

### Ollama unavailable

Start Ollama first:

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

### Long path problems

Enable long paths (admin PowerShell):

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

### Shell behavior differences

Use PowerShell for bootstrap and CLI scripts:

- `./START_HERE.ps1`

---

## Diagnostics

```bash
python --version
uv --version
git --version
uv run python -m backend.cli.entry --help
```

Quick local checks:

```bash
uv run pytest backend/tests/unit/ --tb=short -q
```

---

If the issue persists, open an issue with:

1. Repro steps
2. Exact command used
3. Full error output
4. OS and Python version
5. Redacted `settings.json` fields (`llm_provider`, `llm_model`, base_url presence)
