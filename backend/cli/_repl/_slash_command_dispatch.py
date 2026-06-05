"""Top-level slash-command dispatch for :class:`SlashCommandsMixin`.

The dispatch table maps ``/command`` names to method names on the host
class. ``handle_command`` parses the raw input, ``handle_parsed_command``
routes the parsed command to the matching handler, and
``render_unknown_command`` produces a ``Did you mean ...`` suggestion when
no handler matches.

Kept separate from the mixin so the (long) dispatch table does not crowd
out the per-command handler bodies.
"""

from __future__ import annotations

from typing import Any  # noqa: I001

# Dispatch table for slash commands handled by ``handle_parsed_command``.
# Each method returns ``True`` to keep the REPL running, ``False`` to exit.
# Methods that do not look at ``parsed`` may take ``parsed`` and ignore it.
COMMAND_DISPATCH: dict[str, str] = {
    '/exit': '_cmd_exit',
    '/quit': '_cmd_exit',
    '/settings': '_cmd_settings',
    '/clear': '_cmd_clear',
    '/status': '_cmd_status',
    '/cost': '_cmd_cost',
    '/diff': '_cmd_diff',
    '/checkpoint': '_cmd_checkpoint',
    '/copy': '_cmd_copy',
    '/search': '_cmd_search',
    '/sessions': '_cmd_sessions',
    '/resume': '_cmd_resume',
    '/autonomy': '_cmd_autonomy',
    '/help': '_cmd_help',
    '/model': '_cmd_model',
    '/compact': '_cmd_compact',
    '/retry': '_cmd_retry',
    '/health': '_cmd_health',
    '/add_repo_inst': '_cmd_playbook_passthrough',
    '/address_pr_comments': '_cmd_playbook_passthrough',
    '/api': '_cmd_playbook_passthrough',
    '/audit': '_cmd_playbook_passthrough',
    '/ci': '_cmd_playbook_passthrough',
    '/codereview': '_cmd_playbook_passthrough',
    '/codereview-roasted': '_cmd_playbook_passthrough',
    '/compress': '_cmd_playbook_passthrough',
    '/database': '_cmd_playbook_passthrough',
    '/debug': '_cmd_playbook_passthrough',
    '/docs': '_cmd_playbook_passthrough',
    '/feature': '_cmd_playbook_passthrough',
    '/hardened': '_cmd_playbook_passthrough',
    '/orch-debug': '_cmd_playbook_passthrough',
    '/owasp': '_cmd_playbook_passthrough',
    '/perf': '_cmd_playbook_passthrough',
    '/react': '_cmd_playbook_passthrough',
    '/recover': '_cmd_playbook_passthrough',
    '/refactor': '_cmd_playbook_passthrough',
    '/release': '_cmd_playbook_passthrough',
    '/remember': '_cmd_playbook_passthrough',
    '/security': '_cmd_playbook_passthrough',
    '/testing': '_cmd_playbook_passthrough',
    '/tool': '_cmd_playbook_passthrough',
    '/update_pr_description': '_cmd_playbook_passthrough',
    '/update_test': '_cmd_playbook_passthrough',
}


def handle_command(host: Any, text: str) -> bool:
    """Handle a /command. Returns True to continue REPL, False to exit."""
    from backend.cli.repl import (
        SlashCommandParseError,
        _parse_slash_command,
    )

    try:
        parsed = _parse_slash_command(text)
    except SlashCommandParseError as exc:
        host._warn(str(exc))
        return True
    return handle_parsed_command(host, parsed)


def handle_parsed_command(host: Any, parsed: Any) -> bool:
    """Handle a parsed /command. Returns True to continue, False to exit."""
    method_name = COMMAND_DISPATCH.get(parsed.name)
    if method_name is not None:
        return getattr(host, method_name)(parsed)
    render_unknown_command(host, parsed.raw_name)
    return True


def render_unknown_command(host: Any, raw_cmd: str) -> None:
    from backend.cli.repl import _closest_command_names

    if host._renderer is None:
        return
    suggestion_text = _closest_command_names(raw_cmd)
    suffix = ''
    if suggestion_text:
        rendered_suggestions = ' or '.join(f'`{item}`' for item in suggestion_text)
        suffix = f' Did you mean {rendered_suggestions}?'
    host._renderer.add_system_message(
        f'Unknown command: `{raw_cmd}`.{suffix}\n'
        'Type `/help` to list commands, or press Tab after `/` to autocomplete.',
        title='warning',
    )
