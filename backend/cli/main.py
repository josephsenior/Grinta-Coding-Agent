"""Grinta CLI — zero-config terminal entry point.

Usage::

    grinta              # Launch interactive REPL
    grinta --help       # Show help
    python -m backend.cli.main   # Alternative invocation
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
import time
import warnings
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from backend.core.os_capabilities import OS_CAPS

# Suppress third-party DeprecationWarnings (same default as entry.py / backend pkg).
warnings.filterwarnings('ignore', category=DeprecationWarning)
# google-genai subclasses aiohttp.ClientSession (emits noise on import in some envs).
warnings.filterwarnings(
    'ignore',
    message=r'Inheritance class AiohttpClientSession from ClientSession is discouraged',
    category=DeprecationWarning,
)


def _create_console(*args: Any, **kwargs: Any) -> Any:
    from rich.console import Console as RichConsole

    return RichConsole(*args, **kwargs)


Console = _create_console


def _normalize_project_arg_early(value: str) -> str:
    """Normalize a project arg before backend modules are safe to import."""
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {'"', "'"}:
        normalized = normalized[1:-1].strip()
    if normalized.lower().startswith('file:'):
        parsed = urlparse(normalized)
        path = unquote(parsed.path or '')
        if OS_CAPS.is_windows and len(path) >= 3 and path[0] == '/' and path[2] == ':':
            path = path[1:]
        normalized = path
    return normalized


def _parse_project_dir_from_argv() -> Path | None:
    """Return ``-p`` / ``--project`` directory from ``sys.argv`` if present."""
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('-p', '--project') and i + 1 < len(argv):
            try:
                return Path(_normalize_project_arg_early(argv[i + 1])).expanduser().resolve()
            except OSError:
                return None
        if a.startswith('--project='):
            try:
                return Path(_normalize_project_arg_early(a.split('=', 1)[1])).expanduser().resolve()
            except OSError:
                return None
        i += 1
    return None


def _grinta_install_tree_for_dotenv() -> Path:
    """``backend/cli/main.py`` → parents ``cli``, ``backend``, Grinta repo root."""
    return Path(__file__).resolve().parent.parent.parent


def _load_dotenv_early(*, explicit_project: str | None = None) -> None:
    """Load ``.env`` into ``os.environ`` before backend imports.

    1. **Grinta install** ``<repo>/.env`` — optional keys and overrides (e.g. ``LOG_TO_FILE=false``).
       Logging defaults (``LOG_TO_FILE``, ``DEBUG_LLM``) are on in ``backend.core.constants``.
    2. Optional **``-p`` / explicit project** ``.env`` with ``override=True`` so a
       client repo can override API keys without duplicating logging flags.

    The process **cwd** is intentionally not loaded: launch location stays unrelated
    to where configuration lives.

    Uses ``override=False`` for the Grinta file so real OS environment variables win.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    try:
        load_dotenv(_grinta_install_tree_for_dotenv() / '.env', override=False)
    except OSError:
        pass
    for base in (
        _parse_project_dir_from_argv(),
        Path(explicit_project).expanduser().resolve() if explicit_project else None,
    ):
        if base is None:
            continue
        try:
            load_dotenv(base / '.env', override=True)
        except OSError:
            pass


def _log_to_file_effective() -> bool:
    """Mirror ``LOG_TO_FILE`` default in ``backend.core.constants`` without importing backend."""
    raw = os.getenv('LOG_TO_FILE')
    if raw is not None and raw.strip() != '':
        return raw.strip().lower() in ('true', '1', 'yes')
    return True


def _app_logger_level_after_silence() -> int:
    """Level for ``app`` / ``app.access`` when silencing console noise.

    When ``LOG_TO_FILE`` is enabled, keep the configured log level so
    ``TimedRotatingFileHandler`` still receives INFO/DEBUG records.
    """
    if not _log_to_file_effective():
        return logging.ERROR
    name = os.getenv('LOG_LEVEL', 'INFO').upper()
    # Python 3.11+ provides getLevelNamesMapping(). Fallback for older versions.
    if hasattr(logging, 'getLevelNamesMapping'):
        mapping = logging.getLevelNamesMapping()
    else:
        mapping = logging._levelToName  # type: ignore
    return mapping.get(name, logging.INFO)


# ── Silence logging immediately at import time ──────────────────────
# This MUST run before any backend modules are imported so their
# module-level handlers never write to stdout/stderr.
def _silence_all_loggers() -> None:
    """Nuke every handler that could write to stdout/stderr."""
    root = logging.getLogger()
    for h in root.handlers[:]:
        if isinstance(h, logging.StreamHandler) and not isinstance(
            h, logging.FileHandler
        ):
            root.removeHandler(h)
    root.addHandler(logging.NullHandler())
    root.setLevel(logging.WARNING)

    app_level = _app_logger_level_after_silence()
    for name in ('app', 'app.access'):
        lg = logging.getLogger(name)
        for h in lg.handlers[:]:
            if isinstance(h, logging.StreamHandler) and not isinstance(
                h, logging.FileHandler
            ):
                lg.removeHandler(h)
        lg.addHandler(logging.NullHandler())
        lg.setLevel(app_level)
        lg.propagate = False

    for name in (
        'uvicorn',
        'httpcore',
        'httpx',
        'asyncio',
        'filelock',
        'openai',
        'httpx._client',
        'charset_normalizer',
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)


_load_dotenv_early()
_silence_all_loggers()


def _configure_redirected_streams(*streams: object | None) -> None:
    """Prefer UTF-8 when writing Rich output to redirected streams."""
    if not streams:
        streams = (sys.stdout, sys.stderr)
    for stream in streams:
        if stream is None:
            continue
        if bool(getattr(stream, 'isatty', lambda: True)()):
            continue
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            try:
                reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                # Log or handle reconfiguration failure if necessary, rather than silent continue
                pass


_GRINTA_LOGO_LINES: tuple[str, ...] = (
    r'  [red]▄▄████████████████████████████████▄▄[/red]  ',
    r'[red]▄██████████████████████████████████████▄[/red]',
    r'[red]▀▀▀▀▀▀▀██████████████████████████▀▀▀▀▀▀▀[/red]',
    r'       [red]███[/red][black]▄▄▄▄▄[/black][red]████████████[/red][black]▄▄▄▄▄[/black][red]███[/red]       ',
    r'       [red]███[/red][black]█[/black][black on white]  [/black on white][white on black]▝[/white on black][black]█[/black][red]███[/red][black]▄[/black][red]████[/red][black]▄[/black][red]███[/red][black]█[/black][black on white]  [/black on white][white on black]▝[/white on black][black]█[/black][red]███[/red]       ',
    r'       [red]███[/red][black]█[/black][black on white]   [/black on white][black]█[/black][red]███[/red][black]▀▄▄▄▄▀[/black][red]███[/red][black]█[/black][black on white]   [/black on white][black]█[/black][red]███[/red]       ',
    r'       [red]███[/red][black]▀▀▀▀▀[/black][red]████████████[/red][black]▀▀▀▀▀[/black][red]███[/red]       ',
    r'     [red]▄████████████████████████████▄[/red]     ',
    r'   [red]▄████████████████████████████████▄[/red]   ',
    r'                                        ',
)

_GRINTA_FALLBACK_BANNER: tuple[str, ...] = (
    '  ____ ____  ___ _   _ _____  _',
    ' / ___|  _ \\|_ _| \\ | |_   _|/ \\',
    '| |  _| |_) || ||  \\| | | | / _ \\',
    '| |_| |  _ < | || |\\  | | |/ ___ \\',
    ' \\____|_| \\_\\___|_| \\_| |_/_/   \\_\\',
)


def _build_splash_lines() -> list[Any]:
    from rich.text import Text

    try:
        import pyfiglet as _pyfiglet

        raw = _pyfiglet.figlet_format('GRINTA', font='slant').splitlines()
        while raw and not raw[-1].strip():
            raw.pop()
    except Exception:
        raw = list(_GRINTA_FALLBACK_BANNER)

    logo_width = 40
    text_width = max((len(ln) for ln in raw), default=0)
    width = max(logo_width, text_width)

    lines: list[Any] = []
    for ln in _GRINTA_LOGO_LINES:
        t = Text.from_markup(ln.strip())
        pad = max(0, width - len(t))
        lines.append(Text(' ' * (pad // 2)) + t + Text(' ' * (pad - pad // 2)))
    for ln in raw:
        t = Text(ln, style='bold red')
        pad = max(0, width - len(t))
        lines.append(Text(' ' * (pad // 2)) + t + Text(' ' * (pad - pad // 2)))
    return lines


def show_grinta_splash(console: Any | None = None) -> None:
    """Render the GRINTA boot splash."""
    from rich.align import Align
    from rich.box import ROUNDED
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    console = console or Console()
    _figlet_lines = _build_splash_lines()
    _D = 'dim'

    _TAGLINE = 'AI agent. Pure grit.'
    _HINT = (
        'Type /help for commands · Ctrl+C interrupts the agent · /quit or exit to leave'
    )

    def _body(visible: int, *, tagline: bool = False) -> Group:
        figlet = Text()
        for i, text_obj in enumerate(_figlet_lines):
            if i > 0:
                figlet.append('\n')
            if i < visible:
                figlet.append(text_obj)
            else:
                figlet.append(' ' * len(text_obj))
        parts: list = [Align.center(figlet), Text('')]
        if tagline:
            parts.append(Text(_TAGLINE, style='italic dim', justify='center'))
        else:
            parts.append(Text(''))
        return Group(*parts)

    def _frame(visible: int, *, tagline: bool = False, hint: bool = False) -> Any:
        panel = Panel(
            _body(visible, tagline=tagline),
            title='[bold dim] >_ [/]',
            border_style=_D,
            box=ROUNDED,
            padding=(1, 4),
        )
        rows: list = [Text(''), Align.center(panel), Text('')]
        if hint:
            rows.append(Align.center(Text(_HINT, style='dim')))
            rows.append(Text(''))
        return Group(*rows)

    if not console.is_terminal:
        console.print(_frame(len(_figlet_lines), tagline=True, hint=True))
        return

    from rich.live import Live

    with Live(
        _frame(0), console=console, refresh_per_second=30, transient=False
    ) as live:
        for i in range(1, len(_figlet_lines) + 1):
            live.update(_frame(i))
            time.sleep(0.08)
        live.update(_frame(len(_figlet_lines), tagline=True))
        time.sleep(0.1)
        live.update(_frame(len(_figlet_lines), tagline=True, hint=True))
        time.sleep(0.2)


def _setup_logging() -> None:
    """Re-silence loggers after backend imports add their handlers."""
    _silence_all_loggers()


def _read_piped_stdin() -> str | None:
    """Capture a one-shot piped task before startup work can consume stdin."""
    if bool(getattr(sys.stdin, 'isatty', lambda: True)()):
        return None
    try:
        data = sys.stdin.read()
    except Exception:
        return None
    if data == '':
        return None
    return data


def _version_string() -> str:
    try:
        from backend import get_version

        return get_version()
    except Exception:
        return 'unknown'


def _project_dir_arg(value: str) -> str:
    from backend.core.workspace_resolution import resolve_existing_directory

    try:
        return str(resolve_existing_directory(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _env_truthy(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _resolve_invocation(
    *,
    model: str | None,
    project: str | None,
    no_splash: bool,
) -> tuple[str | None, str | None, bool, bool]:
    """Resolve CLI flags when grinta is invoked as the console script."""
    if model is not None or project is not None or no_splash:
        return model, project, False, no_splash

    argv = sys.argv[1:]
    if not argv:
        return None, None, False, False

    parser = argparse.ArgumentParser(
        prog='grinta',
        description='Grinta — AI coding agent for the terminal',
    )
    parser.add_argument(
        '--model',
        '-m',
        help='Override LLM model (e.g. anthropic/claude-sonnet-4-20250514)',
    )
    parser.add_argument(
        '--project',
        '-p',
        type=_project_dir_arg,
        help='Set project root directory',
    )
    parser.add_argument(
        '--no-splash',
        action='store_true',
        default=False,
        help='Start without the animated splash screen',
    )
    parser.add_argument(
        '--cleanup-storage',
        action='store_true',
        default=False,
        help='Consolidate legacy project data into .grinta/storage and exit',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {_version_string()}',
    )
    args = parser.parse_args(argv)
    if args.cleanup_storage:
        return args.model, args.project, True, args.no_splash
    return args.model, args.project, False, args.no_splash


async def _async_main(
    *,
    model: str | None = None,
    project: str | None = None,
    show_splash: bool = True,
) -> None:
    resolved_project = (
        str(Path(project).resolve()) if project else str(Path.cwd().resolve())
    )
    os.environ['PROJECT_ROOT'] = resolved_project

    from backend.cli.repl import Repl
    from backend.core.config import load_app_config
    from backend.core.logger import configure_file_logging
    from backend.persistence.locations import get_project_local_data_root

    configure_file_logging()
    # Backend imports above trigger module-level logger setup — re-silence.
    _silence_all_loggers()

    console = _build_async_console(show_splash)
    initial_input = _read_piped_stdin()

    try:
        # -- load config -------------------------------------------------------
        config = load_app_config()

        # -- apply CLI overrides (non-persistent) ------------------------------
        _apply_cli_overrides(
            config, model, resolved_project, get_project_local_data_root,
        )

        # -- onboarding if needed ----------------------------------------------
        config = await _ensure_onboarded(
            config, console, model, resolved_project, get_project_local_data_root,
        )
        if config is None:
            return

        # -- launch REPL -------------------------------------------------------
        repl = Repl(config, console)
        if initial_input:
            repl.queue_initial_input(initial_input)
        await repl.run()
    finally:
        from backend.inference.direct_clients import aclose_shared_http_clients

        await aclose_shared_http_clients()


def _build_async_console(show_splash: bool) -> Console:
    try:
        term_cols = shutil.get_terminal_size().columns
    except OSError:
        term_cols = 120
    console = Console(width=term_cols - 2)
    if show_splash and not _env_truthy('GRINTA_NO_SPLASH'):
        show_grinta_splash(console)
    return console


def _apply_cli_overrides(
    config: Any,
    model: str | None,
    resolved_project: str,
    get_project_local_data_root: Any,
) -> None:
    if model:
        llm_cfg = config.get_llm_config()
        llm_cfg.model = model
    config.project_root = resolved_project
    config.local_data_root = get_project_local_data_root(resolved_project)


async def _ensure_onboarded(
    config: Any,
    console: Console,
    model: str | None,
    resolved_project: str,
    get_project_local_data_root: Any,
) -> Any | None:
    from backend.cli.config_manager import (
        auto_detect_api_keys,
        ensure_default_model,
        needs_onboarding,
        run_onboarding,
    )

    if not needs_onboarding(config):
        ensure_default_model(config)
        return config

    detected_provider = auto_detect_api_keys(config)
    if detected_provider and not needs_onboarding(config):
        console.print(
            f'  [green]✓[/green] Auto-detected API key from environment '
            f'([cyan]{detected_provider}[/cyan])',
        )
        console.print(
            '  [dim][bold]Next:[/bold] type [bold]/help[/bold] for commands, '
            '[bold]/settings[/bold] for model and MCP, '
            '[bold]grinta --help[/bold] for CLI flags.[/dim]',
        )
        ensure_default_model(config)
        return config

    config = run_onboarding()
    ensure_default_model(config)
    _apply_cli_overrides(config, model, resolved_project, get_project_local_data_root)
    if needs_onboarding(config):
        console.print('[red]No API key configured. Exiting.[/red]')
        return None
    return config


def main(
    *,
    model: str | None = None,
    project: str | None = None,
    cleanup_storage: bool = False,
    no_splash: bool = False,
) -> None:
    """Synchronous entry point for the ``grinta`` console_script."""
    # Grinta repo ``.env`` first (and optional explicit project), before backend
    # import so ``LOG_TO_FILE`` / ``LOG_LEVEL`` match ``backend.core.constants``.
    _load_dotenv_early(explicit_project=project)
    # Silence all logging immediately — before any backend imports fire their
    # module-level handlers (backend/core/logger.py installs a JSON→stdout
    # handler when imported, which would spew INFO noise into the terminal).
    _setup_logging()
    _configure_redirected_streams()
    if cleanup_storage:
        from backend.cli.storage_cleanup import run_storage_cleanup_command

        run_storage_cleanup_command(project)
        return
    model, project, handled, no_splash = _resolve_invocation(
        model=model,
        project=project,
        no_splash=no_splash,
    )
    if handled:
        from backend.cli.storage_cleanup import run_storage_cleanup_command

        run_storage_cleanup_command(project)
        return
    try:
        asyncio.run(_async_main(model=model, project=project, show_splash=not no_splash))
    except KeyboardInterrupt:
        # Top-level Ctrl+C — exit cleanly without traceback.
        print()  # newline after ^C


if __name__ == '__main__':
    main()
