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
from pathlib import Path

from rich.align import Align
from rich.console import Console, Group
from rich.text import Text

_CRIMSON = 'bold #DC143C'
_PROMPT_WHITE = 'bold #FFFFFF'
_EYE_WHITE = 'bold #FFFFFF'


def _configure_redirected_streams(*streams: io.TextIOBase | None) -> None:
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


def _styled_line(*segments: tuple[str, str]) -> Text:
    line = Text()
    for text, style in segments:
        line.append(text, style=style)
    return line


def show_grinta_splash(console: Console | None = None) -> None:
    """Render the GRINTA boot splash in the terminal."""
    console = console or Console()

    splash = Group(
        Text(''),
        Align.center(
            _styled_line(
                (
                    '                _________________________________                ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    '          ______/                                 \\______          ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                ('         /_____/    ', _CRIMSON),
                (' .-^^^^-. ', _EYE_WHITE),
                ('         ', _CRIMSON),
                (' .-^^^^-. ', _EYE_WHITE),
                ('    \\_____\\         ', _CRIMSON),
            )
        ),
        Align.center(
            _styled_line(
                ('        /_____/    ', _CRIMSON),
                ('/ o  o \\', _EYE_WHITE),
                ('_________', _CRIMSON),
                ('/ o  o \\', _EYE_WHITE),
                ('    \\_____\\        ', _CRIMSON),
            )
        ),
        Align.center(
            _styled_line(
                ('            ||      ', _CRIMSON),
                ('\\  --  /', _EYE_WHITE),
                ('  _____  ', _CRIMSON),
                ('\\  --  /', _EYE_WHITE),
                ('      ||            ', _CRIMSON),
            )
        ),
        Align.center(
            _styled_line(
                ('            ||           \\____/           ||            ', _CRIMSON),
            )
        ),
        Align.center(
            _styled_line(
                ('      _____||_______', _CRIMSON),
                ("'----'", _EYE_WHITE),
                ('  | ', _CRIMSON),
                ('>', _PROMPT_WHITE),
                ('_', _PROMPT_WHITE),
                (' |  ', _CRIMSON),
                ("'----'", _EYE_WHITE),
                ('_______||_____      ', _CRIMSON),
            )
        ),
        Align.center(
            _styled_line(
                (
                    '     /_______________________|_____|_______________________\\     ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    '                 \\              /_____|              /                 ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    '                  \\____________/      \\____________/                  ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    '                   |_____|              |_____|                   ',
                    _CRIMSON,
                ),
            )
        ),
        Text(''),
        Align.center(
            _styled_line(
                (
                    '  GGGGGG   RRRRRR   IIIIIIII  NNN   NN  TTTTTTTT   AAAAAA   ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    ' GG    GG  RR   RR     II     NNNN  NN     TT     AA    AA  ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    ' GG        RRRRRR      II     NN NN NN     TT     AAAAAAAA  ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    ' GG  GGGG  RR  RR      II     NN  NNNN     TT     AA    AA  ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    ' GG    GG  RR   RR     II     NN   NNN     TT     AA    AA  ',
                    _CRIMSON,
                ),
            )
        ),
        Align.center(
            _styled_line(
                (
                    '  GGGGGG   RR    RR  IIIIIIII NN    NN     TT     AA    AA  ',
                    _CRIMSON,
                ),
            )
        ),
        Text(''),
    )

    console.print(splash)


def _setup_logging() -> None:
    """Redirect all backend logging through RichHandler so stray prints don't break the TUI layout."""
    from rich.logging import RichHandler

    handler = RichHandler(
        show_time=False,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        level=logging.WARNING,
    )
    # Replace root handlers.
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.WARNING)

    # Also silence noisy libraries.
    for name in ('uvicorn', 'httpcore', 'httpx', 'asyncio', 'filelock'):
        logging.getLogger(name).setLevel(logging.ERROR)


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
    """Resolve CLI flags when grinta is invoked as the console script.

    ``backend.cli.entry`` already parses these flags before calling ``main()``.
    This fallback keeps ``grinta`` and ``python -m backend.cli.main`` working
    when they are invoked directly.
    """
    if model is not None or project is not None:
        return model, project, False

    argv = sys.argv[1:]
    if not argv:
        return None, None, False

    if argv[0] == 'serve':
        sys.argv = [sys.argv[0]] + argv[1:]
        from backend.embedded import main as serve_main

        serve_main()
        return None, None, True

    parser = argparse.ArgumentParser(
        prog='grinta',
        description='Grinta interactive CLI',
        epilog="Subcommands: 'grinta serve' starts the backend API server.",
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
    args = parser.parse_args(argv)
    return args.model, args.project, False


async def _async_main(
    *,
    model: str | None = None,
    project: str | None = None,
) -> None:
    from backend.cli.config_manager import (
        ensure_default_model,
        needs_onboarding,
        run_onboarding,
    )
    from backend.cli.repl import Repl
    from backend.core.config import load_app_config

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
            config = run_onboarding()
            config.get_agent_config(config.default_agent).cli_mode = True
            ensure_default_model(config)
            if model:
                llm_cfg = config.get_llm_config()
                llm_cfg.model = model
            config.project_root = resolved_project
            # local_data_root intentionally NOT set to project root.
            # Re-check after onboarding.
            if needs_onboarding(config):
                console.print('[red]No API key configured. Exiting.[/red]')
                return
        else:
            ensure_default_model(config)

        # -- redirect backend noise --------------------------------------------
        _setup_logging()

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
) -> None:
    """Synchronous entry point for the ``grinta`` console_script."""
    _configure_redirected_streams(sys.stdout, sys.stderr)
    model, project, handled = _resolve_invocation(model=model, project=project)
    if handled:
        return
    try:
        asyncio.run(_async_main(model=model, project=project))
    except KeyboardInterrupt:
        # Top-level Ctrl+C — exit cleanly without traceback.
        print()  # newline after ^C


if __name__ == '__main__':
    main()
