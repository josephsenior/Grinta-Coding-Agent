"""Native browser tool (browser-use library, in-process)."""

from __future__ import annotations

from typing import Any

from backend.core.enums import ActionSecurityRisk
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition, get_security_risk_param
from backend.ledger.action.browser_tool import BrowserToolAction

BROWSER_TOOL_NAME = 'browser'

_BROWSER_COMMANDS = (
    'start',
    'close',
    'navigate',
    'snapshot',
    'screenshot',
    'click',
    'type',
)

_DESCRIPTION = """\
In-process browser automation (Chromium via browser-use). Grinta is the only planner — this does not run a nested browser agent.

Each call runs one subcommand. Typical flows use multiple calls (e.g. navigate, then snapshot or click/type as needed). `start` is optional; navigate/snapshot can open the session.

Commands:
- start: launch the browser session (optional; navigate/snapshot auto-starts).
- close: stop the browser session.
- navigate: load a URL (http/https only). Completes at navigation commit; run snapshot if you need the fully rendered DOM text.
- snapshot: return an accessibility/DOM text view of the current page (run before click/type to get element indices).
- screenshot: capture PNG; params: full_page (bool, optional). Saves under workspace downloads and returns the path.
- click: params: index (int) — index from the last snapshot.
- type: params: index (int), text (string), clear (bool, default true).

Requires optional dependency: uv sync --group browser, then uvx browser-use install for Chromium (run install first so the first session start is not slow or aborted by timeouts).

Debugging: set environment variable GRINTA_BROWSER_TRACE=1 to print browser stage lines to stderr (the REPL hides normal app logs).
"""


def create_browser_tool() -> ChatCompletionToolParam:
    return create_tool_definition(
        name=BROWSER_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            'command': {
                'type': 'string',
                'enum': list(_BROWSER_COMMANDS),
                'description': (
                    'Single browser step. Issue further browser tool calls until the '
                    'browsing goal is met (not only start).'
                ),
            },
            'url': {
                'type': 'string',
                'description': 'For navigate: full http(s) URL.',
            },
            'new_tab': {
                'type': 'boolean',
                'description': 'For navigate: open in a new tab.',
            },
            'full_page': {
                'type': 'boolean',
                'description': 'For screenshot: capture full scrollable page.',
            },
            'index': {
                'type': 'integer',
                'description': 'For click/type: element index from snapshot.',
            },
            'text': {
                'type': 'string',
                'description': 'For type: text to enter.',
            },
            'clear': {
                'type': 'boolean',
                'description': 'For type: clear field first (default true).',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['command'],
    )


def build_browser_tool_action(arguments: dict[str, Any]) -> BrowserToolAction:
    from backend.core.errors import FunctionCallValidationError

    cmd = str(arguments.get('command') or '').strip().lower()
    if cmd not in _BROWSER_COMMANDS:
        raise FunctionCallValidationError(
            f'Invalid browser command {cmd!r}. Allowed: {", ".join(_BROWSER_COMMANDS)}'
        )
    params: dict[str, Any] = {}
    if 'url' in arguments and arguments['url'] is not None:
        params['url'] = arguments['url']
    if 'new_tab' in arguments:
        params['new_tab'] = arguments['new_tab']
    if 'full_page' in arguments:
        params['full_page'] = arguments['full_page']
    if 'index' in arguments and arguments['index'] is not None:
        params['index'] = arguments['index']
    if 'text' in arguments and arguments['text'] is not None:
        params['text'] = arguments['text']
    if 'clear' in arguments:
        params['clear'] = arguments['clear']

    thought = str(arguments.get('thought') or '')
    # Circuit breaker counts only HIGH; treat read-only / session lifecycle as MEDIUM
    # so browser demos (many start/snapshot) do not trip "too many high-risk actions".
    if cmd in ('navigate', 'click', 'type'):
        risk = ActionSecurityRisk.HIGH
    else:
        risk = ActionSecurityRisk.MEDIUM
    return BrowserToolAction(
        command=cmd, params=params, thought=thought, security_risk=risk
    )
