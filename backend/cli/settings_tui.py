"""Two-tab settings TUI — accessible via /settings command."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
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
    provider_map, custom_idx = _print_provider_menu(console)

    choice = Prompt.ask(
        '  Provider number [dim](Enter to cancel)[/dim]', default='', console=console
    ).strip()
    if not choice:
        console.print(f'[{CLR_META}]  · Cancelled.[/]')
        return False
    try:
        num = int(choice)
    except ValueError:
        console.print(f'[{CLR_STATUS_ERR}]  ✗ Not a number: {choice!r}[/]')
        return False

    selection = _resolve_provider_selection(console, num, provider_map, custom_idx)
    if selection is None:
        return False
    provider_key, base_url = selection

    new_model = Prompt.ask('  Model name', console=console).strip()
    if not new_model:
        console.print(f'[{CLR_META}]  · Cancelled.[/]')
        return False
    if '/' not in new_model and provider_key:
        new_model = f'{provider_key}/{new_model}'

    update_model(new_model, provider=provider_key, base_url=base_url)
    console.print(f'[{CLR_STATUS_OK}]  ✓ Model updated to [bold]{new_model}[/bold].[/]')
    return True


def _print_provider_menu(
    console: Console,
) -> tuple[dict[int, tuple[str, str]], int]:
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
        f'  [{CLR_BRAND}]{custom_idx:>2}[/]  Custom [dim](OpenAI-compatible endpoint)[/dim]'
    )
    console.print()
    return provider_map, custom_idx


def _resolve_provider_selection(
    console: Console,
    num: int,
    provider_map: dict[int, tuple[str, str]],
    custom_idx: int,
) -> tuple[str | None, str | None] | None:
    if num in provider_map:
        provider_key, _ = provider_map[num]
        return provider_key, None
    if num != custom_idx:
        console.print(f'[{CLR_STATUS_ERR}]  ✗ Invalid selection.[/]')
        return None
    provider_key = Prompt.ask(
        '  Provider name [dim](e.g. together)[/dim]', console=console
    ).strip()
    if not provider_key:
        console.print(f'[{CLR_META}]  · Cancelled.[/]')
        return None
    base_url = Prompt.ask(
        '  Base URL [dim](e.g. https://api.together.xyz/v1)[/dim]',
        console=console,
    ).strip()
    if not base_url:
        console.print(
            f'[{CLR_STATUS_ERR}]  ✗ Base URL is required for custom providers.[/]'
        )
        return None
    return provider_key, base_url


def _render_tab_bar(active: int) -> Text:
    """Tab strip — numbers are the keyboard shortcut, dot marks the active tab."""
    bar = Text('  ')
    tabs = ('AI Config', 'MCP Servers')
    for i, label in enumerate(tabs):
        is_active = i == active
        # Bracket the digit so it visually reads as a key affordance, the same
        # way command hints render ``[k] label`` below the panel.
        if is_active:
            bar.append('▌ ', style=f'bold {CLR_BRAND}')
            bar.append(f'[{i + 1}] {label}', style=f'bold {CLR_BRAND}')
            bar.append('  ', style='')
        else:
            bar.append('  ', style='')
            bar.append(f'[{i + 1}]', style=f'dim {CLR_BRAND}')
            bar.append(f' {label}', style=CLR_META)
            bar.append('  ', style='')
        if i != len(tabs) - 1:
            bar.append('   ', style='')
    return bar


def _render_ai_tab(console: Console) -> None:
    config = load_app_config()
    table = Table(
        show_header=False,
        border_style=CLR_CARD_BORDER,
        padding=(1, 2),
        box=box.ROUNDED,
    )
    table.add_column('Field', style=CLR_CARD_TITLE, no_wrap=True)
    table.add_column('Value')
    table.add_column('', style=CLR_META, no_wrap=True)

    provider, model = HUDBar.describe_model(config.get_llm_config().model)
    table.add_row('Provider', provider, '')
    table.add_row('Model', model, Text('[m] change', style=f'dim {CLR_BRAND}'))
    table.add_row(
        'API Key',
        get_masked_api_key(config),
        Text('[k] change', style=f'dim {CLR_BRAND}'),
    )
    table.add_row(
        'Budget/task', get_budget(config), Text('[b] change', style=f'dim {CLR_BRAND}')
    )
    icons = 'on' if get_cli_tool_icons_enabled(config) else 'off'
    table.add_row('Tool icons', icons, Text('[i] toggle', style=f'dim {CLR_BRAND}'))

    console.print(
        Panel(
            table,
            title=f'[{CLR_BRAND}]AI Configuration[/]',
            title_align='left',
            border_style=CLR_CARD_BORDER,
            padding=(1, 2),
        )
    )
    console.print()
    _render_command_hint(
        console,
        [
            ('m', 'model'),
            ('k', 'api key'),
            ('b', 'budget'),
            ('i', 'tool icons'),
            ('2', 'MCP tab'),
            ('q', 'back'),
        ],
    )


def _render_mcp_tab(console: Console) -> None:
    config = load_app_config()
    servers = get_mcp_servers(config)

    table = Table(
        border_style=CLR_CARD_BORDER,
        header_style=CLR_CARD_TITLE,
        padding=(1, 2),
        box=box.ROUNDED,
    )
    table.add_column('#', style=CLR_META, no_wrap=True, justify='right')
    table.add_column('Name', style=CLR_CARD_TITLE, no_wrap=True)
    table.add_column('Type', no_wrap=True)
    table.add_column('Endpoint', overflow='fold')

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
            title_align='left',
            border_style=CLR_CARD_BORDER,
            padding=(1, 2),
        )
    )
    console.print()
    settings_path = _settings_path()
    console.print(
        f'  [{CLR_META}]Saved to [bold]{settings_path}[/bold]  '
        '· edit the [bold]mcp_config[/bold] section for advanced changes.[/]'
    )
    console.print()
    _render_command_hint(
        console,
        [
            ('a', 'add server'),
            ('1', 'AI tab'),
            ('q', 'back'),
        ],
    )


def _render_command_hint(console: Console, items: list[tuple[str, str]]) -> None:
    """Render a consistent ``[k]ey  label  ·  ...`` command hint line."""
    line = Text('  ')
    for idx, (key, label) in enumerate(items):
        if idx > 0:
            line.append('   ·   ', style=CLR_META)
        line.append(f'[{key}]', style=f'bold {CLR_BRAND}')
        line.append(f' {label}', style=CLR_META)
    console.print(line)


def open_settings(console: Console) -> None:
    """Main entry point for the /settings TUI."""
    active_tab = 0
    console.print()
    header = Text()
    header.append(' ⚙ ', style=CLR_BRAND)
    header.append('Settings', style=f'bold {CLR_BRAND}')
    header.append('   model · API keys · MCP servers', style=CLR_META)
    console.print(header)
    # Use a Rule so the divider always spans the terminal — fixed-width
    # ``─ * 56`` looked truncated on wide terminals and overran narrow ones.
    console.print(Rule(style=CLR_CARD_BORDER))

    while True:
        console.print()
        console.print(_render_tab_bar(active_tab))
        console.print(Rule(style=CLR_META))
        console.print()

        if active_tab == 0:
            next_tab = _run_ai_tab(console)
        else:
            next_tab = _run_mcp_tab(console)
        if next_tab is None:
            break
        active_tab = next_tab

    console.print()
    console.print(Rule(style=CLR_CARD_BORDER))
    console.print(f'[{CLR_META}]  Settings closed.[/]')
    console.print()


def _read_settings_command(console: Console) -> str:
    return (
        Prompt.ask(f'[{CLR_BRAND}]settings ›[/]', default='q', console=console)
        .strip()
        .lower()
    )


def _run_ai_tab(console: Console) -> int | None:
    """Render AI tab and process one command. Returns next tab index, or None to quit."""
    _render_ai_tab(console)
    console.print()
    cmd = _read_settings_command(console)
    if cmd == 'q':
        return None
    if cmd == '2':
        return 1
    _dispatch_ai_command(console, cmd)
    return 0


def _dispatch_ai_command(console: Console, cmd: str) -> None:
    if cmd == 'm':
        _prompt_model_change(console)
    elif cmd == 'k':
        _prompt_api_key_change(console)
    elif cmd == 'b':
        _prompt_budget_change(console)
    elif cmd == 'i':
        _toggle_tool_icons(console)
    else:
        _render_unknown_settings_command(console, cmd)


def _render_unknown_settings_command(console: Console, cmd: str) -> None:
    rendered = cmd or '<empty>'
    console.print(f'[{CLR_STATUS_ERR}]  ✗ Unknown settings command: {rendered!r}[/]')
    console.print(
        f'[{CLR_META}]    Use one of the highlighted keys below the panel.[/]'
    )


def _prompt_api_key_change(console: Console) -> None:
    new_key = Prompt.ask(
        '  New API key [dim](input is hidden)[/dim]',
        console=console,
        password=True,
    )
    if new_key.strip():
        update_api_key(new_key.strip())
        console.print(f'[{CLR_STATUS_OK}]  ✓ API key updated.[/]')
    else:
        console.print(f'[{CLR_META}]  · Cancelled.[/]')


def _prompt_budget_change(console: Console) -> None:
    val = Prompt.ask(
        '  Budget per task in USD [dim](e.g. 5.0 — enter 0 for unlimited)[/dim]',
        console=console,
    ).strip()
    if not val:
        console.print(f'[{CLR_META}]  · Cancelled.[/]')
        return
    try:
        budget_val = float(val)
    except ValueError:
        console.print(f'[{CLR_STATUS_ERR}]  ✗ Not a number: {val!r}[/]')
        return
    update_budget(budget_val if budget_val > 0 else None)  # type: ignore[arg-type]
    if budget_val <= 0:
        console.print(f'[{CLR_STATUS_OK}]  ✓ Budget set to unlimited.[/]')
    else:
        console.print(f'[{CLR_STATUS_OK}]  ✓ Budget set to ${budget_val:.2f}/task.[/]')


def _toggle_tool_icons(console: Console) -> None:
    cfg = load_app_config()
    new_val = not get_cli_tool_icons_enabled(cfg)
    update_cli_tool_icons(new_val)
    state = 'on' if new_val else 'off'
    console.print(f'[{CLR_STATUS_OK}]  ✓ Tool icons turned {state}.[/]')


def _run_mcp_tab(console: Console) -> int | None:
    """Render MCP tab and process one command. Returns next tab index, or None to quit."""
    _render_mcp_tab(console)
    console.print()
    cmd = _read_settings_command(console)
    if cmd == 'q':
        return None
    if cmd == '1':
        return 0
    if cmd == 'a':
        _prompt_add_mcp_server(console)
    elif cmd:
        _render_unknown_settings_command(console, cmd)
    return 1


def _prompt_add_mcp_server(console: Console) -> None:
    name = Prompt.ask('  Server name', console=console).strip()
    if not name:
        console.print(f'[{CLR_META}]  · Cancelled.[/]')
        return
    mode = Prompt.ask(
        '  Type', choices=['url', 'command'], default='url', console=console
    )
    if mode == 'url':
        url = Prompt.ask(
            '  Server URL [dim](e.g. https://mcp.example.com/sse)[/dim]',
            console=console,
        ).strip()
        if not url:
            console.print(f'[{CLR_META}]  · Cancelled.[/]')
            return
        add_mcp_server(name, url=url)
        console.print(f'[{CLR_STATUS_OK}]  ✓ Added [bold]{name}[/bold] \u2192 {url}[/]')
    else:
        command = Prompt.ask(
            '  Command [dim](e.g. npx @some/mcp-server)[/dim]', console=console
        ).strip()
        if not command:
            console.print(f'[{CLR_META}]  · Cancelled.[/]')
            return
        add_mcp_server(name, command=command)
        console.print(
            f'[{CLR_STATUS_OK}]  ✓ Added [bold]{name}[/bold] \u2192 {command}[/]'
        )
