"""Per-command handlers for :class:`SlashCommandsMixin`.

Each function corresponds to one ``/command`` and is invoked via a
one-line forwarder method on the mixin. The forwarders are the only
public surface of the mixin; this module contains the actual logic.
"""

from __future__ import annotations

from typing import Any

from backend.cli.config_manager import get_current_model
from backend.cli.hud import HUDBar
from backend.cli.settings_tui import open_settings
from backend.core.config import load_app_config


def cmd_exit(host: Any, parsed: Any) -> bool:
    del parsed
    if host._renderer is not None:
        hud = host._hud.state
        parts = []
        if hud.context_tokens > 0 or hud.llm_calls > 0:
            parts.append(f'{hud.llm_calls} LLM calls')
            parts.append(f'{hud.context_tokens:,} tokens')
            if hud.cost_usd > 0:
                parts.append(f'${hud.cost_usd:.4f}')
            if hud.condensation_count > 0:
                parts.append(f'{hud.condensation_count}x condensed')
            summary = ' · '.join(parts)
            host._renderer.add_system_message(summary, title='session')
        host._renderer.add_system_message('Goodbye.', title='grinta')
    return False


def cmd_settings(host: Any, parsed: Any) -> bool:
    del parsed
    if host._renderer is not None:
        with host._renderer.suspend_live():
            open_settings(host._console)
    else:
        open_settings(host._console)
    host._config = load_app_config()
    host._hud.update_model(get_current_model(host._config))
    if host._renderer is not None:
        host._renderer.set_cli_tool_icons(host._config.cli_tool_icons)
    # Don't add_system_message — settings are navigational, not part of
    # the agentic conversation and should not appear in chat history.
    return True


def cmd_clear(host: Any, parsed: Any) -> bool:
    if host._reject_extra_args(parsed):
        return True
    if host._renderer is not None:
        host._renderer.clear_history()
        host._renderer.add_system_message(
            'Transcript cleared. Send a message, or type `/help` for commands.',
            title='grinta',
        )
    return True


def cmd_sessions(host: Any, parsed: Any) -> bool:
    from backend.cli.session_manager import (
        delete_sessions,
        list_sessions,
        show_session,
    )

    args = list(parsed.args)
    if args and args[0].lower() == 'list':
        args.pop(0)

    search = None
    sort_by = 'updated'
    limit = 20
    preview_idx = None
    delete_targets: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a in ('--search', '-s') and i + 1 < len(args):
            search = args[i + 1]
            i += 2
        elif a in ('--sort',) and i + 1 < len(args):
            allowed = ('updated', 'created', 'events', 'cost', 'model')
            if args[i + 1] in allowed:
                sort_by = args[i + 1]
            else:
                host._warn(f'Sort must be one of: {", ".join(allowed)}')
                return True
            i += 2
        elif a in ('--delete', '-d') and i + 1 < len(args):
            i += 1
            while i < len(args) and not args[i].startswith('-'):
                delete_targets.append(args[i])
                i += 1
        elif a in ('--limit', '-l') and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                host._warn('Limit must be a number.')
                return True
            if limit < 1:
                host._warn('Limit must be 1 or greater.')
                return True
            i += 2
        elif a == '--preview' and i + 1 < len(args):
            preview_idx = args[i + 1]
            i += 2
        else:
            # Positional: session limit (use --preview <N> for preview)
            try:
                parsed_limit = int(a)
            except ValueError:
                host._warn(f'Unknown option: {a}')
                return True
            if parsed_limit < 1:
                host._warn('Limit must be 1 or greater.')
                return True
            limit = parsed_limit
            i += 1

    if delete_targets:
        if host._renderer is not None:
            with host._renderer.suspend_live():
                delete_sessions(host._console, delete_targets, config=host._config)
        else:
            delete_sessions(host._console, delete_targets, config=host._config)
        return True

    if preview_idx is not None:
        if host._renderer is not None:
            with host._renderer.suspend_live():
                found = show_session(
                    host._console, config=host._config, target=preview_idx
                )
                if not found:
                    host._warn(f"No session at '{preview_idx}'")
        else:
            found = show_session(
                host._console, config=host._config, target=preview_idx
            )
            if not found:
                host._warn(f"No session at '{preview_idx}'")
        return True

    if host._renderer is not None:
        with host._renderer.suspend_live():
            list_sessions(
                host._console,
                limit=limit,
                config=host._config,
                sort_by=sort_by,
                search=search,
            )
    else:
        list_sessions(
            host._console,
            limit=limit,
            config=host._config,
            sort_by=sort_by,
            search=search,
        )
    return True


def cmd_resume(host: Any, parsed: Any) -> bool:
    if len(parsed.args) != 1:
        if host._renderer is not None:
            host._renderer.add_system_message(
                'Usage: `/resume <N>` or `/resume <session_id>`.\n'
                'Press Tab after `/resume ` to autocomplete recent sessions.',
                title='warning',
            )
        return True
    host._pending_resume = parsed.args[0]
    return True


def cmd_model(host: Any, parsed: Any) -> bool:
    from backend.cli.config_manager import update_model

    if not parsed.args:
        current = get_current_model(host._config)
        provider, model = HUDBar.describe_model(current)
        if host._renderer is not None:
            host._renderer.add_system_message(
                f'Current provider: {provider}  model: {model}  (use `/model <provider/model>` to switch)',
                title='model',
            )
        return True
    if len(parsed.args) != 1:
        host._warn(f'Usage: {host._usage(parsed.name)}')
        return True
    new_model = parsed.args[0].strip()
    if '/' not in new_model or new_model.startswith('/') or new_model.endswith('/'):
        host._warn('Use a provider-qualified model, for example `openai/gpt-4.1`.')
        return True
    update_model(new_model)
    host._config = load_app_config()
    host._hud.update_model(get_current_model(host._config))
    provider, model = HUDBar.describe_model(get_current_model(host._config))
    if host._renderer is not None:
        host._renderer.add_system_message(
            f'Model switched to provider: {provider}  model: {model}. Changes apply to the next session.',
            title='model',
        )
    return True


def cmd_compact(host: Any, parsed: Any) -> bool:
    if host._reject_extra_args(parsed):
        return True
    from backend.ledger.action.agent import CondensationRequestAction

    host._next_action = CondensationRequestAction()
    return True


def cmd_retry(host: Any, parsed: Any) -> bool:
    if host._reject_extra_args(parsed):
        return True
    if host._last_user_message:
        from backend.ledger.action import MessageAction

        host._next_action = MessageAction(content=host._last_user_message)
    else:
        if host._renderer is not None:
            host._renderer.add_system_message(
                'No previous message to retry.',
                title='warning',
            )
    return True


def cmd_playbook_passthrough(host: Any, parsed: Any) -> bool:
    """Queue a playbook slash command as a normal user turn.

    Playbook slash triggers are matched by memory-level trigger logic, not
    by the REPL command handler itself.
    """
    from backend.ledger.action import MessageAction

    suffix = f' {" ".join(parsed.args)}' if parsed.args else ''
    host._next_action = MessageAction(content=f'{parsed.name}{suffix}')
    return True


def cmd_copy(host: Any, parsed: Any) -> bool:
    from backend.cli.repl import _copy_to_system_clipboard

    if host._reject_extra_args(parsed):
        return True
    last_reply = (
        host._renderer.last_assistant_message_text
        if host._renderer is not None
        else ''
    )
    if not last_reply.strip():
        if host._renderer is not None:
            host._renderer.add_system_message(
                'No assistant reply available to copy yet.',
                title='warning',
            )
        return True
    ok, msg = _copy_to_system_clipboard(last_reply)
    if host._renderer is not None:
        if ok:
            char_count = len(last_reply.strip())
            line_count = last_reply.strip().count('\n') + 1
            host._renderer.add_system_message(
                f'Copied {char_count} characters ({line_count} lines) to clipboard.',
                title='clipboard',
            )
        else:
            host._renderer.add_system_message(msg, title='warning')
    return True


def cmd_search(host: Any, parsed: Any) -> bool:
    """Search the current session transcript for matching text."""
    query = ' '.join(parsed.args).strip()
    if not query:
        host._warn('Usage: /search <text to find>')
        return True
    if host._event_stream is None:
        host._warn('No active session to search.')
        return True
    if host._renderer is None:
        host._warn('Renderer not available.')
        return True

    from rich import box
    from rich.table import Table

    from backend.cli.theme import CLR_BRAND, CLR_CARD_BORDER, CLR_META, STYLE_DIM

    try:
        events = host._event_stream.get_matching_events(
            query=query, limit=20, reverse=True
        )
    except Exception:
        host._warn('Search failed. See logs for details.')
        return True

    if not events:
        host._renderer.add_system_message(
            f'No results found for "{query}".', title='search'
        )
        return True

    table = Table(
        show_header=True,
        header_style=f'bold {CLR_BRAND}',
        box=box.SIMPLE,
        pad_edge=False,
        show_lines=False,
    )
    table.add_column('#', style=STYLE_DIM, width=6, justify='right')
    table.add_column('Type', style=CLR_META, width=18)
    table.add_column('Preview', style=CLR_CARD_BORDER, overflow='fold')

    for evt in events:
        evt_type = (
            type(evt).__name__.replace('Action', '').replace('Observation', '')
        )
        content = getattr(evt, 'content', '') or getattr(evt, 'message', '') or ''
        preview = content.strip()[:120].replace('\n', ' ')
        table.add_row(str(getattr(evt, 'id', '?')), evt_type, preview)

    host._renderer.add_system_message(
        table, title=f'search: "{query}" ({len(events)} results)'
    )
    return True


def cmd_help(host: Any, parsed: Any) -> bool:
    from backend.cli.repl import _build_help_markdown, _build_help_table

    if len(parsed.args) > 1:
        host._warn(f'Usage: {host._usage(parsed.name)}')
        return True

    search_term = None
    show_all = False

    if parsed.args:
        arg = parsed.args[0]
        if arg in ('--all', '-a'):
            show_all = True
        elif arg not in ('--search', '-s'):
            # Specific command requested
            help_text = _build_help_markdown(arg)
            if host._renderer is not None:
                host._renderer.add_markdown_block(
                    'Help',
                    help_text,
                )
            return True

    # Check for search flag
    if parsed.args and parsed.args[0] in ('--search', '-s'):
        search_term = parsed.args[1] if len(parsed.args) > 1 else None

    # Show interactive table (if renderer supports add_renderable)
    table = _build_help_table(search_term, show_all=show_all)
    if host._renderer is not None:
        if hasattr(host._renderer, 'add_renderable'):
            host._renderer.add_renderable(table, force_terminal=True)
        else:
            # Fallback: convert table to string and show as markdown
            from io import StringIO

            from rich.console import Console

            sio = StringIO()
            table_console = Console(file=sio, force_terminal=True, width=100)
            table_console.print(table)
            host._renderer.add_system_message(sio.getvalue().strip(), title='help')
    return True
