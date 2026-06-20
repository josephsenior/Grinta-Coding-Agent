"""Native browser tool (browser-use library, in-process)."""

from __future__ import annotations

from typing import Any

from backend.core.enums import ActionSecurityRisk
from backend.core.tools.tool_names import BROWSER_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.param_defs import (
    create_tool_definition,
    get_security_risk_param,
)
from backend.ledger.action.browser_tool import BrowserToolAction

_BROWSER_COMMANDS = (
    'start',
    'close',
    'navigate',
    'snapshot',
    'screenshot',
    'click',
    'type',
    'scroll',
    'send_keys',
    'wait',
    'switch_tab',
    'close_tab',
    'list_tabs',
    'go_back',
    'extract',
    'upload_file',
    'select_dropdown_option',
)

_DESCRIPTION = """\
In-process browser automation (Chromium via browser-use). Grinta is the only planner — no nested browser agent.

Each call runs one subcommand; chain calls until the browsing goal is met. `start` is optional.

Commands:
- start / close: session lifecycle.
- navigate: http(s) URL; optional new_tab. Optional return_state (default true) appends compact indexed DOM after navigate.
- snapshot: page state; mode=interactive (default), full, or diff (delta of indexed lines vs prior diff snapshot).
- screenshot: JPEG to workspace downloads; full_page, inject_image (default true) for vision models; same LLM consumes the image when vision is enabled.
- click / type: index from snapshot; optional return_state (default true).
- scroll: direction up/down/left/right/top/bottom, optional pixels, optional to_text, optional scroll_index for element scroll.
- send_keys: keys string (e.g. Enter, Tab, Control+a).
- wait: wait_kind timeout|text|selector|network_idle; value for text/selector substring; timeout_sec; optional return_state.
- switch_tab / close_tab: tab index; list_tabs: no params (JSON tab list).
- go_back: history back.
- extract: schema (JSON object) plus optional instruction — structured JSON via the same orchestrator LLM (wired at runtime).
- upload_file: index + path under workspace.
- select_dropdown_option: index plus option_text or option_value.

Requires: python scripts/bootstrap_env.py browser and uvx browser-use install for Chromium.

Debugging: GRINTA_BROWSER_TRACE=1 prints browser stages to stderr.
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
            'return_state': {
                'type': 'boolean',
                'description': (
                    'For navigate, click, type, scroll, send_keys, wait, switch_tab, '
                    'close_tab, go_back: append compact interactive DOM after success '
                    '(default true).'
                ),
            },
            'mode': {
                'type': 'string',
                'enum': ['interactive', 'full', 'diff'],
                'description': 'For snapshot: interactive (default), full DOM text, or diff vs previous diff snapshot.',
            },
            'full_page': {
                'type': 'boolean',
                'description': 'For screenshot: capture full scrollable page.',
            },
            'inject_image': {
                'type': 'boolean',
                'description': (
                    'For screenshot: include JPEG bytes in the observation for the '
                    'active LLM when vision is enabled (default true).'
                ),
            },
            'index': {
                'type': 'integer',
                'description': 'For click/type/upload/select/switch_tab/close_tab: index.',
            },
            'text': {
                'type': 'string',
                'description': 'For type: text to enter.',
            },
            'clear': {
                'type': 'boolean',
                'description': 'For type: clear field first (default true).',
            },
            'direction': {
                'type': 'string',
                'enum': ['up', 'down', 'left', 'right', 'top', 'bottom'],
                'description': 'For scroll: direction (use to_text instead for scroll-to-text).',
            },
            'pixels': {
                'type': 'integer',
                'description': 'For scroll: pixel delta when not using top/bottom/to_text.',
            },
            'to_text': {
                'type': 'string',
                'description': 'For scroll: scroll until this text is found.',
            },
            'scroll_index': {
                'type': 'integer',
                'description': 'For scroll: optional element index to scroll inside.',
            },
            'keys': {
                'type': 'string',
                'description': 'For send_keys: key chord (e.g. Enter, Control+a).',
            },
            'wait_kind': {
                'type': 'string',
                'enum': ['timeout', 'text', 'selector', 'network_idle'],
                'description': 'For wait: strategy (selector uses substring match on DOM text).',
            },
            'wait_for': {
                'type': 'string',
                'enum': ['timeout', 'text', 'selector', 'network_idle'],
                'description': 'Alias for wait_kind.',
            },
            'value': {
                'type': 'string',
                'description': 'For wait text/selector: substring to wait for.',
            },
            'timeout_sec': {
                'type': 'number',
                'description': 'For wait: max seconds.',
            },
            'seconds': {
                'type': 'number',
                'description': 'For wait_kind=timeout: explicit sleep seconds (capped).',
            },
            'path': {
                'type': 'string',
                'description': 'For upload_file: file path under workspace.',
            },
            'option_text': {
                'type': 'string',
                'description': 'For select_dropdown_option: visible option label.',
            },
            'option_value': {
                'type': 'string',
                'description': 'For select_dropdown_option: fallback value string.',
            },
            'schema': {
                'type': 'object',
                'description': 'For extract: JSON Schema describing the output object.',
            },
            'instruction': {
                'type': 'string',
                'description': 'For extract: extra guidance for the extractor.',
            },
            'security_risk': get_security_risk_param(),
        },
        required=['command', 'security_risk'],
    )


def _collect_browser_params(arguments: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    bool_keys = ('new_tab', 'full_page', 'clear', 'return_state', 'inject_image')
    for key in bool_keys:
        if key in arguments:
            params[key] = arguments[key]
    str_keys = (
        'url',
        'text',
        'direction',
        'to_text',
        'keys',
        'wait_kind',
        'wait_for',
        'value',
        'path',
        'option_text',
        'option_value',
        'instruction',
        'mode',
    )
    for key in str_keys:
        val = arguments.get(key)
        if val is not None:
            params[key] = val
    int_keys = ('index', 'pixels', 'scroll_index')
    for key in int_keys:
        val = arguments.get(key)
        if val is not None:
            params[key] = val
    num_keys = ('timeout_sec', 'seconds')
    for key in num_keys:
        val = arguments.get(key)
        if val is not None:
            params[key] = val
    if 'schema' in arguments and arguments['schema'] is not None:
        params['schema'] = arguments['schema']
    return params


def _browser_command_risk(command: str) -> ActionSecurityRisk:
    if command in (
        'navigate',
        'click',
        'type',
        'upload_file',
        'go_back',
    ):
        return ActionSecurityRisk.HIGH
    return ActionSecurityRisk.MEDIUM


def build_browser_tool_action(arguments: dict[str, Any]) -> BrowserToolAction:
    from backend.core.errors import FunctionCallValidationError

    cmd = str(arguments.get('command') or '').strip().lower()
    if cmd not in _BROWSER_COMMANDS:
        raise FunctionCallValidationError(
            f'Invalid browser command {cmd!r}. Allowed: {", ".join(_BROWSER_COMMANDS)}'
        )
    params = _collect_browser_params(arguments)
    thought = str(arguments.get('thought') or '')
    # Circuit breaker counts only HIGH; treat read-only / session lifecycle as MEDIUM
    # so browser demos (many start/snapshot) do not trip "too many high-risk actions".
    risk = _browser_command_risk(cmd)
    return BrowserToolAction(
        command=cmd, params=params, thought=thought, security_risk=risk
    )
