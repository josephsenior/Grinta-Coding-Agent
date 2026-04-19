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

# Suppress third-party DeprecationWarnings (belt-and-suspenders with entry.py).
warnings.filterwarnings('ignore', message='importing.*from.*astroid', category=DeprecationWarning)


def _create_console(*args: Any, **kwargs: Any) -> Any:
    from rich.console import Console as RichConsole

    return RichConsole(*args, **kwargs)


Console = _create_console


def _parse_project_dir_from_argv() -> Path | None:
    """Return ``-p`` / ``--project`` directory from ``sys.argv`` if present."""
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('-p', '--project') and i + 1 < len(argv):
            try:
                return Path(argv[i + 1]).expanduser().resolve()
            except OSError:
                return None
        if a.startswith('--project='):
            try:
                return Path(a.split('=', 1)[1]).expanduser().resolve()
            except OSError:
                return None
        i += 1
    return None


def _grinta_install_tree_for_dotenv() -> Path:
    """``backend/cli/main.py`` → parents ``cli``, ``backend``, Grinta repo root."""
    return Path(__file__).resolve().parent.parent.parent


def _load_dotenv_early(*, explicit_project: str | None = None) -> None:
    """Load ``.env`` into ``os.environ`` before backend imports.

    1. **Grinta install** ``<repo>/.env`` — canonical defaults (``LOG_TO_FILE``, keys).
       You do not need a ``.env`` in every workspace for logging defaults.
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
    return os.getenv('LOG_LEVEL', 'INFO').upper() == 'DEBUG'


def _app_logger_level_after_silence() -> int:
    """Level for ``app`` / ``app.access`` when silencing console noise.

    When ``LOG_TO_FILE`` is enabled, keep the configured log level so
    ``TimedRotatingFileHandler`` still receives INFO/DEBUG records.
    """
    if not _log_to_file_effective():
        return logging.ERROR
    name = os.getenv('LOG_LEVEL', 'INFO').upper()
    mapping = logging.getLevelNamesMapping()
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
        'uvicorn', 'httpcore', 'httpx', 'asyncio', 'filelock',
        'openai', 'httpx._client', 'charset_normalizer',
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
                continue


def show_grinta_splash(console: Any | None = None) -> None:
    """Render the GRINTA boot splash."""
    from rich.align import Align
    from rich.box import ROUNDED
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    console = console or Console()

    _R = 'bold dim'
    _D = 'dim'

    try:
        import pyfiglet as _pyfiglet
        _raw = _pyfiglet.figlet_format('GRINTA', font='slant').splitlines()
        while _raw and not _raw[-1].strip():
            _raw.pop()
        _figlet_lines: list[str] = _raw
    except Exception:
        _figlet_lines = [
            '  ____ ____  ___ _   _ _____  _',
            ' / ___|  _ \\|_ _| \\ | |_   _|/ \\',
            '| |  _| |_) || ||  \\| | | | / _ \\',
            '| |_| |  _ < | || |\\  | | |/ ___ \\',
            ' \\____|_| \\_\\___|_| \\_| |_/_/   \\_\\',
        ]

    _TAGLINE = 'AI agent. Pure grit.'
    _HINT    = 'Type /help to explore commands'

    def _body(visible: int, *, tagline: bool = False) -> Group:
        figlet = Text()
        for i, line in enumerate(_figlet_lines):
            if i > 0:
                figlet.append('\n')
            if i < visible:
                figlet.append(line, style=_R)
            else:
                figlet.append(' ' * len(line))
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

    with Live(_frame(0), console=console, refresh_per_second=30, transient=False) as live:
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


def _resolve_invocation(
    *,
    model: str | None,
    project: str | None,
) -> tuple[str | None, str | None, bool]:
    """Resolve CLI flags when grinta is invoked as the console script."""
    if model is not None or project is not None:
        return model, project, False

    argv = sys.argv[1:]
    if not argv:
        return None, None, False

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
        help='Set project root directory',
    )
    parser.add_argument(
        '--cleanup-storage',
        action='store_true',
        default=False,
        help='Consolidate legacy project data into .grinta/storage and exit',
    )
    args = parser.parse_args(argv)
    if args.cleanup_storage:
        return args.model, args.project, True
    return args.model, args.project, False


async def _async_main(
    *,
    model: str | None = None,
    project: str | None = None,
) -> None:
    resolved_project = (
        str(Path(project).resolve()) if project else str(Path.cwd().resolve())
    )
    os.environ['PROJECT_ROOT'] = resolved_project

    from backend.cli.config_manager import (
        auto_detect_api_keys,
        ensure_default_model,
        needs_onboarding,
        run_onboarding,
    )
    from backend.cli.repl import Repl
    from backend.core.config import load_app_config
    from backend.core.constants import LOG_TO_FILE
    from backend.core.logger import configure_file_logging, get_log_dir
    from backend.persistence.locations import get_project_local_data_root

    configure_file_logging()
    # Backend imports above trigger module-level logger setup — re-silence.
    _silence_all_loggers()

    try:
        term_cols = shutil.get_terminal_size().columns
    except OSError:
        term_cols = 120
    console = Console(width=term_cols - 2)
    show_grinta_splash(console)
    if LOG_TO_FILE:
        console.print(f'  [dim]Session logs: {get_log_dir()}/app.log[/dim]')
    else:
        console.print(
            '  [dim]File logging off — enable in Grinta repo ``.env`` '
            '(``LOG_TO_FILE=true`` or ``LOG_LEVEL=DEBUG``)[/dim]'
        )
    initial_input = _read_piped_stdin()

    # -- load config -------------------------------------------------------
    config = load_app_config()

    # -- apply CLI overrides (non-persistent) ------------------------------
    if model:
        llm_cfg = config.get_llm_config()
        llm_cfg.model = model
    config.project_root = resolved_project
    config.local_data_root = get_project_local_data_root(resolved_project)

    # -- onboarding if needed ----------------------------------------------
    if needs_onboarding(config):
        # Try auto-detecting API keys from environment first
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
        else:
            config = run_onboarding()
            ensure_default_model(config)
            if model:
                llm_cfg = config.get_llm_config()
                llm_cfg.model = model
            config.project_root = resolved_project
            config.local_data_root = get_project_local_data_root(resolved_project)
            # Re-check after onboarding.
            if needs_onboarding(config):
                console.print('[red]No API key configured. Exiting.[/red]')
                return
    else:
        ensure_default_model(config)

    # -- launch REPL -------------------------------------------------------
    repl = Repl(config, console)
    if initial_input:
        repl.queue_initial_input(initial_input)
    await repl.run()


def main(
    *,
    model: str | None = None,
    project: str | None = None,
    cleanup_storage: bool = False,
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
    model, project, handled = _resolve_invocation(model=model, project=project)
    if handled:
        from backend.cli.storage_cleanup import run_storage_cleanup_command
        run_storage_cleanup_command(project)
        return
    try:
        asyncio.run(_async_main(model=model, project=project))
    except KeyboardInterrupt:
        # Top-level Ctrl+C — exit cleanly without traceback.
        print()  # newline after ^C


if __name__ == '__main__':
    main()
