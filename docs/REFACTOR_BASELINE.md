# Refactor baseline metrics

Recorded at the start of the 8.1 → 9.0 improvement plan (Phase 0).
Updated after CLI layout + event-renderer splits.

Re-run these commands after major refactors to track progress.

## Largest CLI files (current)

| File | LOC (approx) |
|------|-----|
| `backend/cli/tui/screen/lifecycle.py` | ~801 |
| `backend/cli/repl/session.py` | ~699 |
| `backend/cli/tui/renderer/mixins/display.py` | ~693 |
| `backend/cli/tui/widgets/activity_card/card.py` | ~684 |
| `backend/cli/tui/renderer/drain.py` | ~656 |
| `backend/cli/tui/screen/input.py` | ~647 |
| `backend/cli/main.py` | ~635 |
| `backend/cli/session/session_manager.py` | ~629 |
| `backend/cli/tool_display/preview.py` | ~615 |

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
| `activity_card.py` (~1,362) | `widgets/activity_card/` package |
| Top-level display/session/settings | `display/`, `session/`, `settings/`, `onboarding/` |

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
