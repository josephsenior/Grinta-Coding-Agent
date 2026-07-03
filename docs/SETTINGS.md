# settings.json reference

Grinta loads a single canonical `settings.json` per installation:

- **pipx / wheel:** `~/.grinta/settings.json` (override with `APP_ROOT`)
- **source checkout:** repository root `settings.json` (unless `APP_ROOT` is set)

Secrets belong in a sibling `.env` file or your shell environment. Reference them from JSON with `"llm_api_key": "${LLM_API_KEY}"`.

## Configuration precedence (highest → lowest)

1. CLI flags (`--model`, `-l`, etc.)
2. `settings.json` values for keys the loader recognizes
3. Environment variables loaded before JSON merge
4. Code defaults

`settings.json` overrides environment variables for the same key. Unknown top-level keys are ignored and logged as warnings.

**LLM API key exception:** when `LLM_API_KEY` is set in the process environment (including via `.env`), it always wins over `settings.json` for runtime authentication. Keep `"llm_api_key": "${LLM_API_KEY}"` in JSON and store the secret in `.env`.

## Top-level keys

| Key | Type | Description |
| --- | --- | --- |
| `llm_provider` | string | Provider id (`openai`, `anthropic`, `ollama`, …) |
| `llm_model` | string | Model id, often `provider/model` |
| `llm_api_key` | string | Use `${LLM_API_KEY}`; literal secrets are discouraged |
| `llm_base_url` | string | Optional OpenAI-compatible base URL |
| `llm_context_window_tokens` | int | Optional explicit context window |
| `llm_max_output_tokens` | int | Optional max output tokens |
| `llm_reasoning_effort` | string | Optional reasoning effort hint |
| `llm_temperature` | number \| null | Global sampling temperature; omit or `null` for provider default |
| `llm_model_temperatures` | object | Per-model temperature overrides (`model id` → number or `null`) |
| `mcp_host` | string | MCP host override |
| `project_root` | string | Default project directory |
| `max_budget_per_task` | number | Per-task USD spend cap |
| `max_iterations` | int | Max agent iterations per task |
| `pending_action_timeout` | number | Tool observation watchdog (seconds) |
| `save_trajectory_path` | string | Trajectory export directory |
| `log_level` | string | Logging level |
| `mcp_config` | object | MCP server definitions (`servers` list) |
| `agent` | object | Per-agent overrides (see below) |
| `security` | object | Runtime hardening (see below) |
| `cli_tool_icons` | bool | Show emoji icons beside tool names in the TUI |

## `agent.<AgentName>` keys

The default agent name is `Orchestrator`. Common overrides:

| Key | Description |
| --- | --- |
| `mode` | `agent`, `chat`, or `plan` |
| `autonomy_level` | `conservative`, `balanced`, or `full` |
| `enable_mcp` | Toggle MCP tools |
| `enable_browsing` | Native `browser` tool (default on; requires `[browser]` extra at runtime). Set `false` to disable. |
| `enable_vector_memory` | Semantic recall / vector store (default on; requires `[rag]` extra at runtime). Set `false` to disable. |
| `enable_hybrid_retrieval` | Hybrid search with `[rag]` (default on; same gating as vector memory). |
| `enable_task_tracker_tool` | Structured plan tracking in Plan mode |
| `enable_lsp_query` | LSP tool (`lsp`); default off — set `true` when language servers are installed |
| `enable_debugger` | Interactive DAP debugger tool; default off — set `true` when debug adapters are available |

**Disabled in v1.0:** `enable_blackboard` and `enable_swarming` — schema only, not wired. Autonomy: [USER_GUIDE.md](USER_GUIDE.md).

See `backend/core/config/agent_config.py` for the full schema.

## `security` keys

| Key | Default | Description |
| --- | --- | --- |
| `windows_shell` | `bash` | On Windows: `bash` (Git Bash) or `powershell` for the agent shell tool |
| `execution_profile` | `standard` | `standard`, `hardened_local`, or `sandboxed_local` |
| `enforce_security` | `true` | Enable security analyzer enforcement |
| `block_high_risk` | `false` | Block HIGH-risk actions outright |
| `allow_network_commands` | `false` | Allow network shell commands in hardened profiles |
| `allow_package_installs` | `false` | Allow package installs in hardened profiles |
| `allow_background_processes` | `false` | Allow background processes in hardened profiles |
| `allow_sensitive_path_access` | `false` | Allow sensitive workspace paths in hardened profiles |
| `allow_read_outside_workspace` | `false` | Opt in to read-only paths outside the project |
| `additional_read_roots` | `[]` | Approved absolute paths when outside reads are enabled |
| `validation_mode` | `permissive` | `permissive` (single-user default) or `strict` conversation ownership |
| `hardened_local_git_allowlist` | `[]` | Git subcommands allowed when `execution_profile` is `hardened_local` |
| `hardened_local_package_allowlist` | `[]` | Package installs allowed in `hardened_local` |
| `hardened_local_network_allowlist` | `[]` | Network command families allowed in `hardened_local` |

Set `APP_STRICT_CONFIG=true` before launch to fail fast on invalid `settings.json` (default: warn and continue with defaults).

### Read-only paths outside the workspace

By default Grinta only reads files inside the open project workspace (plus Grinta’s own data under `~/.grinta/workspaces/<id>/`). To let file-read tools reach sibling directories, shared config, or monorepo packages **without** allowing writes there:

1. Set `security.allow_read_outside_workspace` to `true`.
2. Add explicit absolute paths to `security.additional_read_roots`, for example:

```json
"security": {
  "allow_read_outside_workspace": true,
  "additional_read_roots": [
    "/home/you/monorepo/shared-lib",
    "~/.config/git"
  ]
}
```

Writes remain workspace-scoped. Shell commands (`cat`, `type`, `Get-Content`, etc.) are **not** limited by file-read boundaries in the `standard` execution profile — use `hardened_local` or run in an isolated environment if you need stronger containment.

## `mcp_config`

MCP is **off by default** in `settings.template.json` and in output from `grinta init`. Starter server definitions (shadcn, GitHub, Rigour) are listed with `"enabled": false` so you can turn them on from `/settings` after Node and any required tokens are in place.

| Key | Default | Description |
| --- | --- | --- |
| `enabled` | `false` | Master switch for user-configured MCP servers |
| `servers` | see template | List of stdio/SSE server entries (`enabled` per server) |

Enable MCP when you need external tool servers; base install does not require `npx` or Node.

## Related docs

- [USER_GUIDE.md](USER_GUIDE.md)
- [QUICK_START.md](QUICK_START.md)
- [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md)
- [PERFORMANCE.md](PERFORMANCE.md)
