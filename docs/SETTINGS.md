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
| `enable_browsing` | Toggle browser tools |
| `enable_task_tracker_tool` | Structured plan tracking in Plan mode |

See `backend/core/config/agent_config.py` for the full schema.

## `security` keys

| Key | Default | Description |
| --- | --- | --- |
| `execution_profile` | `standard` | `standard`, `hardened_local`, or `sandboxed_local` |
| `enforce_security` | `true` | Enable security analyzer enforcement |
| `block_high_risk` | `false` | Block HIGH-risk actions outright |
| `allow_network_commands` | `false` | Allow network shell commands in hardened profiles |
| `allow_package_installs` | `false` | Allow package installs in hardened profiles |
| `allow_background_processes` | `false` | Allow background processes in hardened profiles |
| `allow_sensitive_path_access` | `false` | Allow sensitive workspace paths in hardened profiles |
| `allow_read_outside_workspace` | `false` | Opt in to read-only paths outside the project |
| `additional_read_roots` | `[]` | Approved absolute paths when outside reads are enabled |

Writes always remain scoped to the project workspace. File-read boundaries do **not** sandbox shell commands: in Agent mode, `cat`/`type` can still reach paths outside the workspace unless a hardened execution profile blocks them.

## Related docs

- [USER_GUIDE.md](USER_GUIDE.md)
- [INSTALL.md](INSTALL.md)
- [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md)
- [PERFORMANCE.md](PERFORMANCE.md)
