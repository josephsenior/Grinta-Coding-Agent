# Refactor baseline metrics

Recorded at the start of the 8.1 → 9.0 improvement plan (Phase 0).
Updated after CLI layout + event-renderer splits.

Re-run these commands after major refactors to track progress.

## Largest CLI files (current)

| File | LOC (approx) |
|------|-----|
| `backend/cli/tui/renderer/mixins/display.py` | ~881 |
| `backend/cli/tui/screen/lifecycle.py` | ~827 |
| `backend/cli/tui/screen/input.py` | ~760 |
| `backend/cli/session/session_manager.py` | ~697 |
| `backend/cli/repl/session.py` | ~688 |
| `backend/cli/tui/renderer/drain.py` | ~654 |
| `backend/cli/main.py` | ~635 |
| `backend/cli/orient_tools.py` | ~631 |
| `backend/cli/tui/widgets/activity_card/card.py` | ~621 |

**Split complete (no longer monoliths):**

| Was | Now |
|-----|-----|
| `unified_renderer.py` (~1,417) | `event_rendering/unified_renderer/` package |
| `observation_renderers_mixin.py` (~1,166) | `event_rendering/observations/` |
| `action_renderers_mixin.py` (~878) | `event_rendering/actions/` |
| `config_manager.py` (~945) | `settings/` package |
| `_app_renderer_event_processor.py` (~1,992) | `tui/renderer/handlers/*` + processor spine |
| `_app_dialogs.py` (~1,161) | `tui/dialogs/*` |
| `theme.py` (~795) | `theme/` package |
| `activity_card.py` (~1,362) | `widgets/activity_card/` package (`card.py`, `card_styles.py`, `card_content.py`, `card_terminal.py`, …) |
| Top-level display/session/settings | `display/`, `session/`, `settings/`, `onboarding/` |

## Largest non-CLI backend files (current)

| File | LOC (approx) |
|------|-----|
| `backend/inference/direct_clients.py` | ~1,180 |
| `backend/context/conversation_memory.py` | ~1,180 |
| `backend/ledger/stream/__init__.py` | ~1,160 |
| `backend/context/prompt_window.py` | ~1,130 |
| `backend/engine/tools/_file_edits.py` | facade ~72 + submodules |

Post-v1.0 split candidates — use `docs/internals/import-manifest.json` before decomposing.

**Backend splits complete (facade + sibling submodules):**

| Was | Now |
|-----|-----|
| `engine/tools/_file_edits.py` (~1,413) | `_file_edits.py` facade + `_file_edits_{symbols,handlers,multi,common}.py` |
| `inference/llm.py` (~1,060) | `llm.py` facade + `llm_{exceptions,stream,config,core}.py` |
| `context/canonical_state.py` (~1,084) | `canonical_state.py` facade + `canonical_state_{types,ops,private}.py` |
| `context/context_pipeline.py` (~1,251) | `context/context_pipeline/` package (`__init__.py`, `types`, `helpers`, `core_*` mixins) |
| `context/canonical_state.py` (~1,084) | `context/canonical_state/` package (`types`, `ops`, `private`) |
| `inference/llm.py` (~1,060) | `inference/llm/` package (`core`, `config`, `exceptions`, `stream`, `utils`) |
| `inference/direct_clients_*_ops.py` | `inference/providers/` (`openai_ops`, `anthropic_ops`, `gemini_ops`, …) |
| CLI orphans (`syntax_theme`, `layout_tokens`, …) | `cli/theme/`, `cli/display/`, `cli/tool_display/`, `cli/repl/`, `cli/session/` |
| Context memory (`session_memory`, `conversation_memory`, …) | `context/memory/` (`agent_memory`, `conversation_memory`, `session_memory`, `types`, `working_set`, `session_context`) |
| Context processors / compaction / prompt | `context/processors/`, `context/compaction/`, `context/prompt/` |
| Ledger stream infra + `EventStream` | `ledger/stream/` (`__init__.py` = `EventStream`, plus `persistence`, `backpressure`, `coalescing`, …) |
| Ledger config, integrity, masking, tool metadata | `ledger/infra/` (`adapter`, `config`, `integrity`, `secret_masker`, `tool`) |
| Execution runtime pool / factory / orchestrator | `execution/runtime/` (`manager`, `pool`, `factory`, `orchestrator`) |
| Inference capabilities + prompt caching | `inference/capabilities/` (`ModelCapabilities`, `model_features`, `context_limits`, …), `inference/caching/` |
| Execution AES helpers | `execution/aes/` (`helpers`, `file_operations`, `structured_edit_errors`, `security_enforcement`) |
| Retired execution HTTP server | `execution/server/` route/file-viewer layer removed |
| Utils tree-sitter editor + syntax | `utils/treesitter/` (`treesitter_editor`, `syntax_check`, `chunk_localizer`, `_tse_*`) |
| Utils async bridging + retries | `utils/async_helpers/` (`async_utils`, `retry`, `circuit_breaker`, `tenacity_*`, `subprocess_bridge`) — not `async/` (`async` is a reserved keyword) |
| Utils LSP client + language aliases | `utils/lsp/` (`lsp_client`, `language_tool_aliases`) |
| Utils HTTP session + stdio JSON-RPC | `utils/http/` (`http_session`, `stdio_json_rpc`) |
| Utils terminal colors + shell contract | `utils/terminal/` (`term_color`, `terminal_contract`) |
| Orchestration stuck detection | `orchestration/stuck/` (`__init__.py` = `StuckDetector`, `patterns.py`) |
| Orchestration agent + autonomy | `orchestration/agent/` (`__init__.py` = `Agent`, `tools`, `circuit_breaker`, `autonomy`) |
| Orchestration file edits | `orchestration/file_edits/` (`file_edit_transaction`, `file_state_tracker`, `pre_exec_diff`) |
| Orchestration telemetry | `orchestration/telemetry/` (`tool_telemetry`, `conversation_stats`, `progress_tracker`) |
| Orchestration middleware (consolidated) | root `rollback_middleware`, `tool_result_validator` → `middleware/` |
| Execution utils git / file editor / shell | `execution/utils/git/`, `file_editor/` (`__init__.py` = `FileEditor`), `shell/` |

## Commands to refresh

```bash
# Largest backend/cli Python files
uv run python -c "
from pathlib import Path
rows = sorted(
    ((len(p.read_text(encoding='utf-8').splitlines()), p) for p in Path('backend/cli').rglob('*.py')),
    reverse=True,
)
for n, p in rows[:20]:
    print(f'{n:5d}  {p.as_posix()}')
"

# Unit test duration (top 20 slowest)
PYTHONPATH=. uv run pytest backend/tests/unit/cli/ -q --durations=20

# File size advisory
uv run python backend/scripts/verify/check_file_size.py
```

## Phase deliverables

### Phase 0 — foundation

- [x] `docs/CLI_MODULE_MAP.md`
- [x] `docs/REFACTOR_BASELINE.md`
- [x] `backend/scripts/verify/check_file_size.py`

### Phase 1 — CLI/TUI splits

- [x] `backend/cli/theme/` package
- [x] `backend/cli/tui/widgets/activity_card/` package
- [x] `backend/cli/tui/renderer/` handlers + screen/ layout
- [x] `backend/cli/tui/dialogs/` package
- [x] `event_rendering/unified_renderer/` package
- [x] `event_rendering/observations/` + `actions/` packages
- [x] Cosmetic rename: `event_rendering/`, `tool_display/`, `repl/` (no leading `_`)
- [x] `config_manager.py` → `settings/` submodules

### Phase 2 — test mirror

- [x] `backend/tests/unit/cli/tui/`
- [x] `backend/tests/unit/cli/frontend/`
- [x] Orchestration service tests consolidated under `backend/tests/unit/orchestration/services/`

### Phase 3 — top-level CLI packages

- [x] `backend/cli/display/`
- [x] `backend/cli/session/`
- [x] `backend/cli/settings/`
- [x] `backend/cli/onboarding/`

## Import conventions

- `from backend.cli.theme import …` — theme tokens
- `from backend.cli.display.hud import HUDBar` (or submodules under `display/`)
- `from backend.cli.session import session_manager`
- `from backend.cli.repl.slash_command_registry import …` — slash helpers (not `repl`)
- `from backend.cli.event_rendering.observations import ObservationRenderersMixin`
- `from backend.ledger.infra.config import …` — event config, integrity, masking, tool metadata
- `from backend.ledger.stream import EventStream`
- `from backend.utils.treesitter.treesitter_editor import TreeSitterEditor`
- `from backend.utils.async_helpers.async_utils import call_async_from_sync`
- `from backend.utils import retry` — re-exported from `async_helpers/retry`
- `from backend.utils.lsp.lsp_client import get_lsp_client`
- `from backend.utils.http.http_session import HttpSession`
- `from backend.utils.terminal.terminal_contract import get_terminal_tool_name`
- `from backend.orchestration.agent import Agent` — package unchanged
- `from backend.orchestration.stuck import StuckDetector`
- `from backend.orchestration.middleware.rollback_middleware import RollbackMiddleware`
- `from backend.execution.utils.file_editor import FileEditor` — package unchanged
- `from backend.execution.utils.shell.unified_shell import BaseShellSession`
- `from backend.execution.utils.git.git_handler import GitHandler`
- `from backend.execution.utils.tool_registry import …` — host OS binaries (not `engine.tool_registry`)
