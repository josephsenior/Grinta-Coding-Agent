"""Grinta CLI — zero-config terminal entry point.

Usage::

    grinta              # Launch interactive REPL
    grinta --help       # Show help
    python -m backend.cli.main   # Alternative invocation
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from rich.console import Console as Console  # noqa: PLC0414

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
    from rich.theme import Theme as RichTheme

    from backend.cli.theme import grinta_rich_theme_styles, no_color_enabled

    kwargs.setdefault('no_color', no_color_enabled())
    kwargs.setdefault('theme', RichTheme(grinta_rich_theme_styles()))
    return RichConsole(*args, **kwargs)


Console = _create_console  # type: ignore[misc,assignment]


def _normalize_project_arg_early(value: str) -> str:
    """Normalize a project arg before backend modules are safe to import."""
    normalized = value.strip()
    if (
        len(normalized) >= 2
        and normalized[0] == normalized[-1]
        and normalized[0] in {'"', "'"}
    ):
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
                return (
                    Path(_normalize_project_arg_early(argv[i + 1]))
                    .expanduser()
                    .resolve()
                )
            except OSError:
                return None
        if a.startswith('--project='):
            try:
                return (
                    Path(_normalize_project_arg_early(a.split('=', 1)[1]))
                    .expanduser()
                    .resolve()
                )
            except OSError:
                return None
        i += 1
    return None


def _app_settings_dotenv_path() -> Path:
    """Return the canonical ``.env`` path next to ``settings.json``."""
    from backend.core.app_paths import get_app_settings_root

    return Path(get_app_settings_root()) / '.env'


def _load_dotenv_early(*, explicit_project: str | None = None) -> None:
    """Load ``.env`` into ``os.environ`` before backend imports.

    1. **App settings** ``<settings_root>/.env`` — where ``grinta init`` writes secrets
       (``~/.grinta/.env`` for pipx installs, repo root for source checkouts).
       Logging defaults are defined in ``backend.core.constants``; raw LLM debug logging is off by default.
    2. Optional **``-p`` / explicit project** ``.env`` with ``override=True`` so a
       client repo can override API keys without duplicating logging flags.

    The process **cwd** is intentionally not loaded: launch location stays unrelated
    to where configuration lives.

    Uses ``override=False`` for the settings file so real OS environment variables win.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    try:
        load_dotenv(_app_settings_dotenv_path(), override=False)
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

    text_width = max((len(ln) for ln in raw), default=0)

    lines: list[Any] = []
    for ln in raw:
        from backend.cli.theme import CLR_SPLASH_FIGLET

        t = Text(ln, style=CLR_SPLASH_FIGLET)
        pad = max(0, text_width - len(t))
        lines.append(Text(' ' * (pad // 2)) + t + Text(' ' * (pad - pad // 2)))
    return lines


def _is_returning_user() -> bool:
    """Check if the user has run grinta before (history file exists)."""
    from backend.cli.repl.slash_registry_parsing import _HISTORY_FILE

    return _HISTORY_FILE.exists()


def show_grinta_splash(console: Any | None = None, *, compact: bool = False) -> None:
    """Render the GRINTA boot splash with instrumentation-style branding.

    Parameters
    ----------
    console:
        Rich console to print to.
    compact:
        When True, show a condensed 2-line version for returning users.
    """
    from rich.align import Align
    from rich.text import Text

    console = console or Console()
    from backend.cli.theme import CLR_META, STYLE_DIM

    if compact:
        _compact_splash(console)
        return

    ascii_lines = _build_splash_lines()
    figlet_text = Text()
    for i, line in enumerate(ascii_lines):
        if i > 0:
            figlet_text.append('\n')
        figlet_text.append(line)

    _TAGLINE = 'AI coding agent for the terminal.'
    _HINT = 'Describe a task  ·  /help  ·  /settings  ·  /sessions  ·  /quit'

    console.print()
    console.print(Align.center(figlet_text))
    console.print()
    console.print(Align.center(Text(_TAGLINE, style=CLR_META)))
    console.print()
    console.print(Align.center(Text(_HINT, style=STYLE_DIM)))
    console.print()


def _compact_splash(console: Any) -> None:
    """Print a cleaner compact splash for returning users."""
    from rich.align import Align
    from rich.text import Text

    from backend.cli.theme import CLR_BRAND, CLR_META, STYLE_DIM

    console.print()
    console.print(Align.center(Text('GRINTA', style=CLR_BRAND)))
    console.print()
    console.print(
        Align.center(Text('AI coding agent for the terminal.', style=CLR_META))
    )
    console.print()
    console.print(
        Align.center(
            Text(
                'Describe a task  ·  /help  ·  /sessions  ·  /quit',
                style=STYLE_DIM,
            )
        )
    )
    console.print()


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

    from backend.cli.entry import build_parser

    parser = build_parser(include_subcommands=False)
    args = parser.parse_args(argv)
    if args.cleanup_storage:
        return args.model, args.project, True, args.no_splash
    return args.model, args.project, False, args.no_splash


def _resolve_launch_project(project: str | None) -> str:
    from backend.core.workspace_resolution import resolve_launch_project_directory

    return str(resolve_launch_project_directory(project))


async def _async_main(
    *,
    model: str | None = None,
    project: str | None = None,
    show_splash: bool = True,
    minimal: bool = False,
    accessible: bool = False,
    theme: str | None = None,
    verbose: bool = False,
) -> None:
    from backend.core.config import load_app_config
    from backend.core.logging.logger import configure_file_logging
    from backend.persistence.locations import get_project_local_data_root

    resolved_project = _resolve_launch_project(project)
    os.environ['PROJECT_ROOT'] = resolved_project
    # configure_file_logging is idempotent — caller in main() may have already
    # set it up so we can log as early as possible.
    configure_file_logging()
    # Backend imports above trigger module-level logger setup — re-silence.
    _silence_all_loggers()

    _accessible_mode = accessible or _env_truthy('GRINTA_ACCESSIBLE')
    if _accessible_mode:
        os.environ['GRINTA_NO_COLOR'] = '1'
        os.environ['GRINTA_ASCII'] = '1'
        os.environ['GRINTA_NO_SPLASH_ANIM'] = '1'
    if theme:
        os.environ['GRINTA_THEME'] = theme
        from backend.cli.theme import set_theme_preset

        set_theme_preset(theme)
    if verbose:
        os.environ['GRINTA_VERBOSE'] = '1'
    # -- console setup ---------------------------------------------------------
    # Only show CLI splash if not going to TUI to avoid terminal noise
    is_tty = sys.stdin.isatty()
    console = _build_async_console(show_splash and not _accessible_mode and not is_tty)
    initial_input = _read_piped_stdin()

    try:
        # -- load config -------------------------------------------------------
        config = load_app_config()
        config._minimal_mode = minimal  # Store for REPL to pick up
        config._accessible_mode = _accessible_mode  # Store for REPL to pick up

        # -- apply CLI overrides (non-persistent) ------------------------------
        _apply_cli_overrides(
            config,
            model,
            resolved_project,
            get_project_local_data_root,
        )

        # -- onboarding if needed ----------------------------------------------
        config_or_none: Any = await _ensure_onboarded(
            config,
            console,
            model,
            resolved_project,
            get_project_local_data_root,
        )
        if config_or_none is None:
            return
        config = config_or_none

        # -- detect TTY and route to TUI or fallback --------------------------
        if sys.stdin.isatty():
            from backend.cli.tui.main import _async_main_tui

            await _async_main_tui(
                config=config,
                console=console,
                model=model,
                show_splash=False,
                minimal=minimal,
                accessible=_accessible_mode,
                verbose=verbose,
            )
        else:
            from backend.cli.repl.noninteractive import run_noninteractive

            await run_noninteractive(
                config=config,
                console=console,
                initial_input=initial_input,
                verbose=verbose,
            )
    finally:
        from backend.inference.clients import aclose_shared_http_clients

        await aclose_shared_http_clients()


def _build_async_console(show_splash: bool) -> Console:
    try:
        term_cols = shutil.get_terminal_size().columns
    except OSError:
        term_cols = 120
    console = Console(width=term_cols - 2)
    if show_splash and not _env_truthy('GRINTA_NO_SPLASH'):
        returning = _is_returning_user()
        show_grinta_splash(console, compact=returning)
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
    from backend.cli.settings import (
        auto_detect_api_keys,
        ensure_default_model,
        needs_onboarding,
        persist_env_detected_settings,
        run_onboarding,
    )

    if not needs_onboarding(config):
        ensure_default_model(config)
        return config

    from backend.cli.theme import (
        CLR_STATUS_ERR,
        MSG_STYLE_PROVIDER_HINT,
        MSG_STYLE_SUCCESS_MARK,
        STYLE_DIM,
        mark_ok,
    )

    detected_provider = auto_detect_api_keys(config)
    if detected_provider and not needs_onboarding(config):
        llm_cfg = config.get_llm_config()
        api_key = None
        if llm_cfg.api_key is not None:
            api_key = (
                llm_cfg.api_key.get_secret_value()
                if hasattr(llm_cfg.api_key, 'get_secret_value')
                else str(llm_cfg.api_key)
            )
        if persist_env_detected_settings(
            config,
            detected_provider,
            api_key=api_key,
        ):
            console.print(
                f'  [{MSG_STYLE_SUCCESS_MARK}]{mark_ok()}[/] Saved detected credentials '
                'to [bold]settings.json[/bold] for future runs.',
            )
        console.print(
            f'  [{MSG_STYLE_SUCCESS_MARK}]{mark_ok()}[/] Auto-detected API key from '
            f'environment ([{MSG_STYLE_PROVIDER_HINT}]{detected_provider}[/])',
        )
        console.print(
            f'  [{STYLE_DIM}][bold]Next:[/bold] REPL: [bold]/help[/bold], '
            '[bold]/settings[/bold]. Shell: [bold]grinta --help[/bold], '
            f'[bold]grinta sessions list[/bold].[/{STYLE_DIM}]',
        )
        ensure_default_model(config)
        return config

    config = run_onboarding()
    ensure_default_model(config)
    _apply_cli_overrides(config, model, resolved_project, get_project_local_data_root)
    if needs_onboarding(config):
        console.print(
            f'[{CLR_STATUS_ERR}]No API key configured. Run `grinta init` to configure '
            'provider, model, and API key.[/]'
        )
        return None
    return config


def main(
    *,
    model: str | None = None,
    project: str | None = None,
    cleanup_storage: bool = False,
    no_splash: bool = False,
    minimal: bool = False,
    accessible: bool = False,
    theme: str | None = None,
    verbose: bool = False,
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
        from backend.cli.session.storage_cleanup import run_storage_cleanup_command

        run_storage_cleanup_command(project)
        return
    model, project, handled, no_splash = _resolve_invocation(
        model=model,
        project=project,
        no_splash=no_splash,
    )
    if handled:
        from backend.cli.session.storage_cleanup import run_storage_cleanup_command

        run_storage_cleanup_command(project)
        return

    # Resolve project root early so file logging targets the right workspace
    # directory before any diagnostic or REPL code runs.
    resolved_project = _resolve_launch_project(project)
    os.environ['PROJECT_ROOT'] = resolved_project
    from backend.core.runtime_paths import pin_grinta_runtime_paths

    repo_root = pin_grinta_runtime_paths()
    from backend.core.logging.logger import configure_file_logging

    configure_file_logging()

    from backend.cli.repl.debug import debug as diag

    try:
        async_kwargs = {
            'model': model,
            'project': project,
            'show_splash': not no_splash,
        }
        if minimal:
            async_kwargs['minimal'] = minimal
        if accessible:
            async_kwargs['accessible'] = accessible
        if theme:
            async_kwargs['theme'] = theme
        if verbose:
            async_kwargs['verbose'] = verbose

        diag('main() calling asyncio.run')

        # Bump recursion limit for Python 3.12+ Task.cancel() which recursively
        # cancels _fut_waiter chains (nested gathers can exceed the 1000 default).
        import sys

        sys.setrecursionlimit(5000)

        asyncio.run(_async_main(**async_kwargs))  # type: ignore[arg-type]
        diag('main() asyncio.run returned normally')
    except KeyboardInterrupt:
        # Top-level Ctrl+C — exit cleanly without traceback.
        print()  # newline after ^C
    except BaseException:
        import traceback

        logger = logging.getLogger('app')
        logger.debug('main() UNCAUGHT EXCEPTION', exc_info=True)
        traceback.print_exc()
        try:
            from rich.console import Console as RichConsole

            rc = RichConsole()
            rc.print('[red]Fatal error:[/] see stderr for traceback')
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
