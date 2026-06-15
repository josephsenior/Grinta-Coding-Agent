# CLI module map (refactor target layout)

This document tracks the intended module layout for the Grinta CLI/TUI layer.

## Current layout

```
backend/cli/
├── main.py, entry.py              # Entry surfaces
├── event_renderer.py              # CLIEventRenderer facade
├── theme/                         # Visual tokens (import backend.cli.theme)
├── display/                       # HUD, transcript, tool headlines, diff
│   ├── hud.py
│   ├── status_chrome.py
│   ├── reasoning_display.py
│   ├── transcript.py
│   ├── notifications.py
│   ├── diff_renderer.py
│   └── tool_call_display.py
├── session/
│   ├── session_manager.py
│   └── sessions_cli.py
├── settings/                      # App settings I/O, onboarding, MCP
│   ├── constants.py, storage.py, query.py
│   ├── onboarding.py, mcp.py
│   ├── settings_tui.py
│   └── confirmation.py
├── onboarding/
│   └── init_wizard.py
├── repl/                          # REPL session + slash commands
│   ├── session.py                 # Repl class (public: from backend.cli.repl import Repl)
│   ├── slash_command_registry.py
│   └── …                          # mixins, slash_command_*, run_helpers_*
├── tool_display/                  # Rich tool renderers
├── event_rendering/
│   ├── unified_renderer/          # ActivityCard + ActivityRenderer
│   ├── observations/              # CLI observation handlers (domain mixins)
│   ├── actions/                   # CLI action handlers (domain mixins)
│   └── …                          # panels, sidebar, error_panel, mixins
└── tui/                           # Textual application
    ├── app.py
    ├── screen/                    # lifecycle, input, welcome, …
    ├── renderer/                  # processor, drain, handlers/, mixins/
    ├── dialogs/
    └── widgets/
```

## Import conventions

- **Theme:** `from backend.cli.theme import …` (package root only)
- **Display:** `from backend.cli.display.hud import HUDBar`, etc.
- **Sessions:** `from backend.cli.session import session_manager`
- **Settings:** `from backend.cli.settings import get_current_model`, etc.
- **Settings UI:** `from backend.cli.settings.settings_tui import …`
- **REPL:** `from backend.cli.repl import Repl`
- **Activity cards:** `from backend.cli.event_rendering.unified_renderer import ActivityRenderer`
- **Event renderer mixins:** `from backend.cli.event_rendering.observations import ObservationRenderersMixin`
- **Slash commands:** `from backend.cli.repl.slash_command_registry import …`
- **TUI dialogs:** `from backend.cli.tui.dialogs import …`
- **TUI renderer:** `from backend.cli.tui.renderer.processor import …`

## Size budget

| Scope | Soft limit | Hard limit (new/changed files) |
|-------|------------|--------------------------------|
| `backend/cli/**/*.py` (excl. tests) | 500 LOC | 800 LOC |

Advisory: `backend/scripts/verify/check_file_size.py`

## Tests

```
backend/tests/unit/cli/
├── frontend/     # REPL, HUD, event renderer
└── tui/          # Headless TUI
```

Run: `pytest backend/tests/unit/cli -q`

## Intentionally not split (semantic cohesion)

These files are over the soft limit but kept whole:

- `tui/screen/lifecycle.py` (~800)
- `tui/renderer/drain.py`, `tui/screen/input.py`, `tui/renderer/mixins/display.py`

## Mixin conventions

TUI and file-editor splits use `{Host}{Concern}Mixin` class names aligned with
their module (`screen/lifecycle.py` → `ScreenLifecycleMixin`,
`renderer/mixins/display.py` → `RendererDisplayMixin`).

## Future work

| Area | Notes |
|------|-------|
| `screen/communicate.py` | Maintained for `communicate_with_user` action types; `ask_user` covers newer flows |
| Integration-fast CI | Optional speedup |
| Mypy ratchet | Type-check tightening |
