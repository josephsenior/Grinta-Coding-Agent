# Mode Switching — Entry Points and Sync Functions

Grinta exposes three orthogonal mode knobs. This document maps how each is
defined, switched at runtime, persisted, and enforced.

For confirmation architecture see [confirmation-autonomy.md](confirmation-autonomy.md).

## Summary

| Knob | Config key | Runtime switch? | Toolset rebuild? |
| --- | --- | --- | --- |
| Interaction mode | `agent.<name>.mode` | Yes (HUD, `/mode`) | Yes |
| Autonomy | `agent.<name>.autonomy_level` | Yes (HUD, `/autonomy`) | Yes (after fix) |
| Execution profile | `security.execution_profile` | No — restart required | N/A |

## Interaction mode (`chat` / `plan` / `agent`)

**Definition:** `backend/core/interaction_modes.py`, `AgentConfig.mode`

**User surfaces:**

| Surface | Handler |
| --- | --- |
| TUI HUD | `backend/cli/tui/screen/settings.py` → `_apply_mode` |
| `/mode` | `backend/cli/repl/slash_command_status.py` → `apply_interaction_mode` |
| `settings.json` | `backend/cli/settings/query.py` → `update_interaction_mode` |

**Sync on startup:** `backend/cli/settings/bootstrap_sync.py` →
`sync_persisted_interaction_mode_to_controller` →
`backend/cli/settings/query.py`

**Runtime apply:** `backend/cli/settings/mode_runtime.py` →
`apply_interaction_mode_to_controller`:

1. `rebuild_agent_toolset(agent, mode=mode)` — filters tools per mode
2. `sync_active_run_mode_extra_data(controller, mode)`
3. `emit_session_context_if_changed()`

**Enforcement:** `backend/engine/planner.py` → `build_toolset` /
`_filter_tools_for_mode`

## Autonomy (`conservative` / `balanced` / `full`)

**Definition:** `backend/core/autonomy.py`, `AgentConfig.autonomy_level`

**User surfaces:**

| Surface | Handler |
| --- | --- |
| TUI HUD (Agent mode only) | `backend/cli/tui/screen/settings.py` → `_apply_autonomy_level` |
| `/autonomy` | `backend/cli/repl/slash_command_status.py` → `apply_autonomy_level` |
| `settings.json` | `backend/cli/settings/query.py` → `update_autonomy_level` |

**Sync on startup:** `bootstrap_sync.py` → `sync_persisted_autonomy_to_controller`

**Runtime apply:** `backend/cli/settings/mode_runtime.py` →
`apply_autonomy_to_controller`:

1. Updates `AutonomyController`, `AgentConfig`, and HUD (callers)
2. `rebuild_agent_toolset(agent)` — relaxes `security_risk` in tool schemas when full
3. System notice via `autonomy_runtime_notice()` (confirmation + `security_risk` policy)

**Enforcement:**

- Confirmation: `backend/orchestration/services/safety_service.py` (sole policy layer)
- `security_risk` parse scope: `backend/engine/executor_mixins/_executor_response_mixin.py`
- Tool schema: `backend/engine/tools/param_defs.py` → `relax_security_risk_in_tools`

**Legacy alias:** `supervised` in `settings.json` is migrated to `conservative` on read.

## Execution profile (`standard` / `hardened_local` / `sandboxed_local`)

**Definition:** `backend/core/config/security_config.py` → `execution_profile`

**User surfaces:**

| Surface | Supported? |
| --- | --- |
| Edit `settings.json` + restart | Yes |
| `grinta doctor` | Validates profile and sandbox backend |
| TUI HUD / `/settings` | No |
| `/hardened` slash | No (playbook shortcut only) |
| Settings file watcher | No (MCP reload only) |
| `bootstrap_sync` | No |

**Load:** `backend/core/config/config_loader.py` → `_apply_json_security_config`
(invalid values recorded in `ConfigLoadSummary`; fatal under `APP_STRICT_CONFIG`)

**Enforcement (frozen at runtime connect):**

- `backend/execution/aes/security_enforcement.py` — policy gates
- `backend/execution/sandboxing.py` — profile predicates + OS sandbox
- `backend/execution/utils/shell/unified_shell.py` — sandbox policy per session

## Shared bootstrap

`backend/cli/settings/bootstrap_sync.py` → `sync_controller_persisted_settings`
applies persisted **interaction mode** and **autonomy** only (not execution profile).
