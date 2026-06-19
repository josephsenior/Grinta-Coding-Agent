"""Module-level constants for backend.cli.tui.app.

Extracted from app.py to keep the main module under
the per-file LOC budget. Pure code motion.
"""

from __future__ import annotations

import logging
import os
import re

_tui_logger = logging.getLogger('grinta.tui')
_tui_logger.setLevel(logging.DEBUG)


def _bounded_int_env(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        _tui_logger.warning('Invalid %s=%r; using default %d', name, raw, default)
        return default


_TUI_PENDING_EVENT_LIMIT = _bounded_int_env(
    'GRINTA_TUI_PENDING_EVENT_LIMIT',
    default=5000,
    minimum=100,
)
_TUI_HISTORY_RENDER_LIMIT = _bounded_int_env(
    'GRINTA_TUI_HISTORY_RENDER_LIMIT',
    default=2000,
    minimum=200,
)
_FILE_DIFF_AUTO_COLLAPSE_LINES = _bounded_int_env(
    'GRINTA_TUI_FILE_DIFF_AUTO_COLLAPSE_LINES',
    default=80,
    minimum=20,
)
_TUI_DRAIN_FRAME_BUDGET_SECONDS = float(
    os.getenv('GRINTA_TUI_DRAIN_FRAME_BUDGET_SECONDS', '0.016')
)
_TUI_DRAIN_INVOCATION_BUDGET_SECONDS = float(
    os.getenv('GRINTA_TUI_DRAIN_INVOCATION_BUDGET_SECONDS', '0.012')
)
_TUI_TERMINAL_DISPLAY_LINE_CAP = _bounded_int_env(
    'GRINTA_TUI_TERMINAL_DISPLAY_LINE_CAP',
    default=500,
    minimum=50,
)
_TUI_VIEWPORT_MAX_MOUNTED = _bounded_int_env(
    'GRINTA_TUI_VIEWPORT_MAX_MOUNTED',
    default=80,
    minimum=40,
)
_TUI_VIEWPORT_OVERSCAN = _bounded_int_env(
    'GRINTA_TUI_VIEWPORT_OVERSCAN',
    default=20,
    minimum=5,
)
_TUI_RESUME_HYDRATE_EVENTS = _bounded_int_env(
    'GRINTA_TUI_RESUME_HYDRATE_EVENTS',
    default=80,
    minimum=10,
)

_TERMINAL_MOUSE_REPORT_RE = re.compile(r'(?:\x1b)?\[(?:<)?\d{1,7};\d{1,7};\d{1,7}[mM]')
_TERMINAL_ORPHAN_PARAM_TOKEN_RE = re.compile(
    r'(?:^|(?<=[^\w]))(?:\[?\d+(?:;\d+){2,}[OI]?_){2,}'
)

_WELCOME_SUGGESTIONS = [
    'Explain this codebase',
    'Analyze this repository and produce an implementation plan',
    'Plan a safe refactor of this module',
    'Run tests and fix failures',
    'Inspect the project and propose a testing strategy',
]

_WELCOME_SUGGESTION_DETAILS = [
    'Map the architecture, entry points, and important files.',
    'Scan the repo, identify risks, and turn findings into ordered next steps.',
    'Find ownership boundaries, migration steps, and a rollback path.',
    'Run the relevant suite, summarize failures, and make focused fixes.',
    'Spot coverage gaps and recommend the smallest useful test set.',
]

_WELCOME_FIGLET_FALLBACK = (
    '  ____ ____  ___ _   _ _____  _ ',
    ' / ___|  _ \\|_ _| \\ | |_   _|/ \\',
    '| |  _| |_) || ||  \\| | | | / _ \\',
    '| |_| |  _ < | || |\\  | | |/ ___ \\',
    ' \\____|_| \\_\\___|_| \\_| |_/_/   \\_\\',
)

_WELCOME_FIGLET_CACHE: str | None = None
