# Grinta User Guide

This guide reflects the current CLI-first Grinta workflow.

Canonical startup:

- CLI: `uv run python -m backend.cli.entry`
- Optional raw HTTP backend: `uv run python -m backend.execution.action_execution_server 3000 --working-dir .`

## Table of Contents

1. Installation
2. Configuration
3. First Task
4. Optional Raw HTTP Backend
5. LLM Provider Setup
6. Safety and Runtime Model
7. Useful Commands

---

## Installation

### Prerequisites

- Python 3.12+
- uv
- Git

### Install

```bash
uv sync
```

### Create local settings

```bash
cp settings.template.json settings.json
```

On Windows PowerShell:

```powershell
Copy-Item settings.template.json settings.json
```

---

## Configuration

Grinta supports layered configuration, but the default local path uses `settings.json`.

### Minimal settings.json

```json
{
  "llm_provider": "openai",
  "llm_model": "openai/gpt-4o-mini",
  "llm_api_key": "sk-...",
  "llm_base_url": ""
}
```

Notes:

- `llm_provider` can be omitted when `llm_model` includes a provider prefix.
- `llm_base_url` is optional and useful for OpenAI-compatible proxies.
- Environment variables still work and can override advanced settings.

Common environment variables:

- `LLM_API_KEY`
- `LLM_MODEL`
- `APP_ROOT` (forces where `settings.json` is resolved)

---

## First Task

### Start the CLI

```bash
uv run python -m backend.cli.entry
```

### Ask for work

Example:

```text
Add tests for backend/inference/provider_resolver.py and run them.
```

The agent will plan, execute tools, validate progress, and only finish when completion checks pass.

### Project-local state

Session and runtime state are stored under:

- `.grinta/storage`

---

## Optional Raw HTTP Backend

Only start this when you need API/OpenAPI tooling.

### Start backend

Windows:

```powershell
.\start_backend.ps1
```

Cross-platform:

```bash
uv run python -m backend.execution.action_execution_server 3000 --working-dir .
```

### Useful endpoints

- `GET /openapi.json`
- `GET /server_info`
- `POST /execute_action`
- `POST /list_files`
- `POST /upload_file`
- `GET /download_files`

Example:

```bash
curl http://localhost:3000/server_info
```

---

## LLM Provider Setup

Grinta supports direct SDK routing plus OpenAI-compatible endpoints.

### Examples

OpenAI:

```json
{
  "llm_model": "openai/gpt-4o-mini",
  "llm_api_key": "sk-..."
}
```

Anthropic:

```json
{
  "llm_model": "anthropic/claude-sonnet-4-20250514",
  "llm_api_key": "sk-ant-..."
}
```

Google:

```json
{
  "llm_model": "google/gemini-2.5-pro",
  "llm_api_key": "AIza..."
}
```

Ollama local:

```json
{
  "llm_model": "ollama/llama3.2",
  "llm_api_key": ""
}
```

If you use local providers, start them first (for example `ollama serve`).

---

## Safety and Runtime Model

Grinta executes locally on your host machine.

- Default mode is local execution.
- `hardened_local` adds stricter policy checks.
- `hardened_local` is not sandboxing or process isolation.

Use Grinta in trusted repositories and environments.

---

## Useful Commands

Install + run:

```bash
uv sync
uv run python -m backend.cli.entry
```

Backend help:

```bash
uv run python -m backend.execution.action_execution_server --help
```

CLI help:

```bash
uv run python -m backend.cli.entry --help
```

---

For architecture internals, see `docs/ARCHITECTURE.md`.
For contributor-facing internals, see `docs/DEVELOPER.md`.
For historical decisions and pivots, see `docs/journey/README.md`.
