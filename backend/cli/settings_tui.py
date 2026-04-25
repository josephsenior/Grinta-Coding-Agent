"""Two-tab settings TUI — accessible via /settings command."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from backend.cli.config_manager import (
    _PROVIDERS,
    _settings_path,
    add_mcp_server,
    get_budget,
    get_cli_tool_icons_enabled,
    get_masked_api_key,
    get_mcp_servers,
    update_api_key,
    update_budget,
    update_cli_tool_icons,
    update_model,
)
from backend.cli.hud import HUDBar
from backend.cli.theme import (
    CLR_BRAND,
    CLR_CARD_BORDER,
    CLR_CARD_TITLE,
    CLR_META,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
)
from backend.core.config import load_app_config


def _prompt_model_change(console: Console) -> bool:
    """Prompt user to change model via Provider → Model flow. Returns True if changed."""
    console.print()
    console.print('[bold]Select provider:[/bold]')

    idx = 1
    provider_map: dict[int, tuple[str, str]] = {}
    for key, label, _ in _PROVIDERS:
        console.print(f'  [{CLR_BRAND}]{idx:>2}[/]  {label}')
        provider_map[idx] = (key, label)
        idx += 1
    custom_idx = idx
    console.print(
        f'  [{CLR_BRAND}]{custom_idx:>2}[/]  [dim]Custom (OpenAI-compatible)[/dim]'
    )
    console.print()

    choice = Prompt.ask('  Provider number', default='', console=console).strip()
    if not choice:
        return False
    try:
        num = int(choice)
    except ValueError:
        console.print(f'[{CLR_STATUS_ERR}]  Invalid selection.[/]')
        return False

    base_url: str | None = None
    provider_key: str | None = None

    if num in provider_map:
        provider_key, _ = provider_map[num]
    elif num == custom_idx:
        provider_key = Prompt.ask(
            '  Provider name [dim](e.g. together)[/dim]', console=console
        ).strip()
        if not provider_key:
            return False
        base_url = Prompt.ask(
            '  Base URL [dim](e.g. https://api.together.xyz/v1)[/dim]', console=console
        ).strip()
        if not base_url:
            console.print(
                f'[{CLR_STATUS_ERR}]  Base URL is required for custom providers.[/]'
            )
            return False
    else:
        console.print(f'[{CLR_STATUS_ERR}]  Invalid selection.[/]')
        return False

    new_model = Prompt.ask('  Model name', console=console).strip()
    if not new_model:
        return False

    if '/' not in new_model and provider_key:
        new_model = f'{provider_key}/{new_model}'

    update_model(new_model, provider=provider_key, base_url=base_url)
    console.print(f'[{CLR_STATUS_OK}]  Model updated.[/]')
    return True


def _render_tab_bar(active: int) -> Text:
    bar = Text()
    tabs = [(' 1  AI Config ', 'ai'), (' 2  MCP Servers ', 'mcp')]
    for i, (label, _) in enumerate(tabs):
        if i == active:
            bar.append(label, style=CLR_BRAND)
        else:
            bar.append(label, style=CLR_META)
        bar.append('  ')
    return bar


def _render_ai_tab(console: Console) -> None:
    config = load_app_config()
    table = Table(show_header=False, border_style=CLR_CARD_BORDER, padding=(0, 2))
    table.add_column('Field', style=CLR_CARD_TITLE)
    table.add_column('Value')

    provider, model = HUDBar.describe_model(config.get_llm_config().model)
    table.add_row('Provider', provider)
    table.add_row('Model', model)
    table.add_row('API Key', get_masked_api_key(config))
    table.add_row('Budget/task', get_budget(config))
    icons = 'on' if get_cli_tool_icons_enabled(config) else 'off'
    table.add_row('Tool icons', icons)

    console.print(
        Panel(
            table,
            title=f'[{CLR_BRAND}]AI Configuration[/]',
            border_style=CLR_CARD_BORDER,
        )
    )
    console.print()
    console.print(
        f'[{CLR_META}]Commands:  [bold]m[/bold] model  │  [bold]k[/bold] api key  │  [bold]b[/bold] budget  │  '
        '[bold]i[/bold] tool icons  │  [bold]q[/bold] back[/]'
    )


def _render_mcp_tab(console: Console) -> None:
    config = load_app_config()
    servers = get_mcp_servers(config)

    table = Table(border_style=CLR_CARD_BORDER, padding=(0, 2))
    table.add_column('#', style=CLR_META)
    table.add_column('Name', style=CLR_CARD_TITLE)
    table.add_column('Type')
    table.add_column('Endpoint')

    if not servers:
        table.add_row('—', '(no servers configured)', '', '')
    else:
        for i, s in enumerate(servers, 1):
            endpoint = s.get('url') or s.get('command') or '—'
            table.add_row(str(i), s['name'], s.get('type', '?'), str(endpoint))

    console.print(
        Panel(
            table,
            title=f'[{CLR_BRAND}]MCP Servers[/]',
            border_style=CLR_CARD_BORDER,
        )
    )
    console.print()
    settings_path = _settings_path()
    console.print(
        f'[{CLR_META}]Servers are stored as [bold]mcp_config[/bold] in [bold]{settings_path}[/bold] '
        '(you can also edit that file directly).[/]'
    )
    console.print()
    console.print(
        f'[{CLR_META}]Commands:  [bold]a[/bold] add server  │  [bold]q[/bold] back[/]'
    )


def _handle_ai_command(console: Console) -> bool:
    """Handle a single command in the AI tab. Returns False to exit settings."""
    cmd = (
        Prompt.ask('[bold]settings/ai[/bold]', default='q', console=console)
        .strip()
        .lower()
    )
    if cmd == 'q':
        return False
    if cmd == 'm':
        _prompt_model_change(console)
    elif cmd == 'k':
        new_key = Prompt.ask('  New API key', console=console)
        if new_key.strip():
            update_api_key(new_key.strip())
            console.print(f'[{CLR_STATUS_OK}]  API key updated.[/]')
    elif cmd == 'b':
        val = Prompt.ask(
            '  Budget per task in USD [dim](e.g. 5.0 — enter 0 for unlimited)[/dim]',
            console=console,
        ).strip()
        try:
            budget_val = float(val)
            update_budget(budget_val if budget_val > 0 else None)  # type: ignore[arg-type]
            console.print(f'[{CLR_STATUS_OK}]  Budget updated.[/]')
        except ValueError:
            console.print(f'[{CLR_STATUS_ERR}]  Invalid number.[/]')
    elif cmd == 'i':
        cfg = load_app_config()
        new_val = not get_cli_tool_icons_enabled(cfg)
        update_cli_tool_icons(new_val)
        state = 'on' if new_val else 'off'
        console.print(f'[{CLR_STATUS_OK}]  Tool icons {state}.[/]')
    return True


def _handle_mcp_command(console: Console) -> bool:
    """Handle a single command in the MCP tab. Returns False to exit settings."""
    cmd = (
        Prompt.ask('[bold]settings/mcp[/bold]', default='q', console=console)
        .strip()
        .lower()
    )
    if cmd == 'q':
        return False
    if cmd == 'a':
        name = Prompt.ask('  Server name', console=console)
        if not name.strip():
            return True
        mode = Prompt.ask(
            '  Type', choices=['url', 'command'], default='url', console=console
        )
        if mode == 'url':
            url = Prompt.ask(
                '  Server URL (e.g. https://mcp.example.com/sse)', console=console
            )
            if url.strip():
                add_mcp_server(name.strip(), url=url.strip())
                console.print(f'[{CLR_STATUS_OK}]  Server added.[/]')
        else:
            command = Prompt.ask(
                '  Command (e.g. npx @some/mcp-server)', console=console
            )
            if command.strip():
                add_mcp_server(name.strip(), command=command.strip())
                console.print(f'[{CLR_STATUS_OK}]  Server added.[/]')
    return True


def open_settings(console: Console) -> None:
    """Main entry point for the /settings TUI."""
    active_tab = 0
    console.print()
    console.print(
        Panel(
            Text('Settings', style=CLR_BRAND),
            border_style=CLR_CARD_BORDER,
            padding=(0, 2),
        ),
        justify='center',
    )

    while True:
        console.print()
        console.print(_render_tab_bar(active_tab))
        console.print()

        if active_tab == 0:
            _render_ai_tab(console)
            console.print()
            cmd = (
                Prompt.ask(
                    '[bold]settings[/bold]',
                    default='q',
                    console=console,
                )
                .strip()
                .lower()
            )
            if cmd == 'q':
                break
            if cmd == '2':
                active_tab = 1
                continue
            if cmd == 'm':
                _prompt_model_change(console)
            elif cmd == 'k':
                new_key = Prompt.ask('  New API key', console=console)
                if new_key.strip():
                    update_api_key(new_key.strip())
                    console.print(f'[{CLR_STATUS_OK}]  API key updated.[/]')
            elif cmd == 'b':
                val = Prompt.ask(
                    '  Budget per task in USD [dim](e.g. 5.0 — enter 0 for unlimited)[/dim]',
                    console=console,
                ).strip()
                try:
                    budget_val = float(val)
                    update_budget(budget_val if budget_val > 0 else None)  # type: ignore[arg-type]
                    console.print(f'[{CLR_STATUS_OK}]  Budget updated.[/]')
                except ValueError:
                    console.print(f'[{CLR_STATUS_ERR}]  Invalid number.[/]')
            elif cmd == 'i':
                cfg = load_app_config()
                new_val = not get_cli_tool_icons_enabled(cfg)
                update_cli_tool_icons(new_val)
                state = 'on' if new_val else 'off'
                console.print(f'[{CLR_STATUS_OK}]  Tool icons {state}.[/]')
        else:
            _render_mcp_tab(console)
            console.print()
            cmd = (
                Prompt.ask(
                    '[bold]settings[/bold]',
                    default='q',
                    console=console,
                )
                .strip()
                .lower()
            )
            if cmd == 'q':
                break
            if cmd == '1':
                active_tab = 0
                continue
            if cmd == 'a':
                name = Prompt.ask('  Server name', console=console)
                if not name.strip():
                    continue
                mode = Prompt.ask(
                    '  Type', choices=['url', 'command'], default='url', console=console
                )
                if mode == 'url':
                    url = Prompt.ask('  Server URL', console=console)
                    if url.strip():
                        add_mcp_server(name.strip(), url=url.strip())
                        console.print(f'[{CLR_STATUS_OK}]  Server added.[/]')
                else:
                    command = Prompt.ask('  Command', console=console)
                    if command.strip():
                        add_mcp_server(name.strip(), command=command.strip())
                        console.print(f'[{CLR_STATUS_OK}]  Server added.[/]')

    console.print(f'[{CLR_META}]Settings closed.[/]')
