"""Grinta CLI — zero-config terminal entry point.

Usage::

    grinta              # Launch interactive REPL
    grinta --help       # Show help
    python -m backend.cli.main   # Alternative invocation
"""

from __future__ import annotations

import argparse
import asyncio
import io
import logging
import os
import sys
import warnings
from pathlib import Path
from typing import IO

# Suppress third-party DeprecationWarnings (belt-and-suspenders with entry.py).
warnings.filterwarnings('ignore', message='importing.*from.*astroid', category=DeprecationWarning)

import time

from rich.align import Align
from rich.console import Console, Group
from rich.text import Text


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

    for name in ('app', 'app.access'):
        lg = logging.getLogger(name)
        for h in lg.handlers[:]:
            if isinstance(h, logging.StreamHandler) and not isinstance(
                h, logging.FileHandler
            ):
                lg.removeHandler(h)
        lg.addHandler(logging.NullHandler())
        lg.setLevel(logging.ERROR)
        lg.propagate = False

    for name in (
        'uvicorn', 'httpcore', 'httpx', 'asyncio', 'filelock',
        'openai', 'httpx._client', 'charset_normalizer',
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)


_silence_all_loggers()


def _configure_redirected_streams(*streams: io.TextIOBase | IO[str] | None) -> None:
    """Prefer UTF-8 when writing Rich output to redirected streams."""
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


def show_grinta_splash(console: Console | None = None) -> None:
    """Render the GRINTA boot splash — animated drop-in on TTY, static otherwise."""
    from rich.live import Live

    console = console or Console()

    _LINES = [
        ' ██████  ██████  ██ ██    ██ ████████  █████  ',
        '██       ██   ██ ██ ███   ██    ██    ██   ██ ',
        '██  ███  ██████  ██ ██ ██ ██    ██    ███████ ',
        '██   ██  ██  ██  ██ ██  ████    ██    ██   ██ ',
        ' ██████  ██   ██ ██ ██   ███    ██    ██   ██ ',
    ]
    _SUBTITLE = 'think · code · ship'
    _HINT     = 'Type a task or press Tab after / for commands'

    def _frame(visible: int, *, subtitle: bool = False, flash: bool = False) -> Group:
        style = 'bold white' if flash else 'bold red'
        rows: list = [Text('')]
        for i, line in enumerate(_LINES):
            rows.append(Align.center(Text(line if i < visible else '', style=style)))
        rows.append(Text(''))
        if subtitle:
            rows.append(Align.center(Text(_SUBTITLE, style='bold red')))
            rows.append(Align.center(Text(_HINT, style='dim')))
        else:
            rows.append(Text(''))
            rows.append(Text(''))
        rows.append(Text(''))
        return Group(*rows)

    # Non-interactive (piped / redirected): print static splash and return.
    if not console.is_terminal:
        console.print(_frame(len(_LINES), subtitle=True))
        return

    # Animated: lines drop in one by one, brief flash, subtitle fades in.
    with Live(_frame(0), console=console, refresh_per_second=30, transient=False) as live:
        for i in range(1, len(_LINES) + 1):
            live.update(_frame(i))
            time.sleep(0.055)
        # Quick white flash → settle to red
        live.update(_frame(len(_LINES), flash=True))
        time.sleep(0.08)
        live.update(_frame(len(_LINES)))
        time.sleep(0.06)
        # Subtitle appears
        live.update(_frame(len(_LINES), subtitle=True))
        time.sleep(0.15)


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
        help='Migrate legacy project-local storage to the global Grinta data directory',
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
    from backend.cli.config_manager import (
        auto_detect_api_keys,
        ensure_default_model,
        needs_onboarding,
        run_onboarding,
    )
    from backend.cli.repl import Repl
    from backend.core.config import load_app_config

    # Backend imports above trigger module-level logger setup — re-silence.
    _silence_all_loggers()

    console = Console()
    show_grinta_splash(console)
    initial_input = _read_piped_stdin()

    # -- load config -------------------------------------------------------
    previous_cli_mode = os.environ.get('AGENT_CLI_MODE')
    os.environ['AGENT_CLI_MODE'] = 'true'
    try:
        config = load_app_config()
        config.get_agent_config(config.default_agent).cli_mode = True

        # -- apply CLI overrides (non-persistent) ------------------------------
        if model:
            llm_cfg = config.get_llm_config()
            llm_cfg.model = model
        resolved_project = (
            str(Path(project).resolve()) if project else str(Path.cwd().resolve())
        )
        config.project_root = resolved_project
        # local_data_root intentionally NOT overridden here — it stays at the
        # user-level default (~/.grinta/storage) so Grinta never pollutes the
        # user's workspace with sessions/ or storage/ directories.

        # -- onboarding if needed ----------------------------------------------
        if needs_onboarding(config):
            # Try auto-detecting API keys from environment first
            detected_provider = auto_detect_api_keys(config)
            if detected_provider and not needs_onboarding(config):
                console.print(
                    f'  [green]✓[/green] Auto-detected API key from environment '
                    f'([cyan]{detected_provider}[/cyan])',
                )
                ensure_default_model(config)
            else:
                config = run_onboarding()
                config.get_agent_config(config.default_agent).cli_mode = True
                ensure_default_model(config)
                if model:
                    llm_cfg = config.get_llm_config()
                    llm_cfg.model = model
                config.project_root = resolved_project
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
    finally:
        if previous_cli_mode is None:
            os.environ.pop('AGENT_CLI_MODE', None)
        else:
            os.environ['AGENT_CLI_MODE'] = previous_cli_mode


def main(
    *,
    model: str | None = None,
    project: str | None = None,
    cleanup_storage: bool = False,
) -> None:
    """Synchronous entry point for the ``grinta`` console_script."""
    # Silence all logging immediately — before any backend imports fire their
    # module-level handlers (backend/core/logger.py installs a JSON→stdout
    # handler when imported, which would spew INFO noise into the terminal).
    _setup_logging()
    _configure_redirected_streams(sys.stdout, sys.stderr)
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
