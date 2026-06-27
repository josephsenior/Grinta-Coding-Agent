"""Unified CLI entry point for the ``grinta`` console script.

Usage::

    grinta                           # Launch interactive REPL
    grinta init                      # First-run setup wizard
    grinta sessions list             # List past sessions
    grinta sessions show <N|id>      # Show one session's metadata
    grinta sessions export <N|id> <path>  # Export a session to dir/.zip
    grinta sessions delete <N|id> [--yes]
    grinta sessions prune [--days 30] [--yes]
    grinta --model anthropic/...     # Override model
    grinta --project /path/to/repo   # Set project root
    grinta --cleanup-storage         # Consolidate legacy storage into the canonical workspace store
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import warnings
from pathlib import Path

# Pin install paths before any backend import resolves logging or settings.
from backend.core.runtime_paths import pin_grinta_runtime_paths

pin_grinta_runtime_paths()

# Suppress ALL DeprecationWarnings before any package is imported.
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings(
    'ignore',
    message=r'Inheritance class AiohttpClientSession from ClientSession is discouraged',
    category=DeprecationWarning,
)


_EPILOG = """examples:
  grinta
      Start the interactive REPL in the current directory.
  grinta --no-splash
      Start the REPL without the animated splash screen.
    grinta init
      Run the first-run wizard to configure your LLM provider.
  grinta init --non-interactive
      Write settings from LLM_API_KEY / LLM_PROVIDER env vars (CI and scripts).
  grinta doctor
      Run install/config/toolchain diagnostics (non-interactive).
  grinta --project /path/to/repo sessions list
      List sessions for an explicit project root.
  grinta sessions list
      List past sessions (REPL: /sessions, /resume <id>).
  grinta sessions prune --days 30 --yes
      Delete sessions older than 30 days, no prompt.
  grinta -p .
      Same, with an explicit project root (current directory).
  grinta -p /path/to/repo -m anthropic/claude-sonnet-4-6
      Use that project folder and override the model for this session only.
  grinta --cleanup-storage
      Consolidate legacy project data into the canonical workspace store and exit.

In the REPL: /help for slash commands, /settings for model and keys.
Environment: NO_COLOR=1 or GRINTA_NO_COLOR=1 disables color;
GRINTA_ASCII=1 uses ASCII markers; GRINTA_NO_SPLASH_ANIM=1 skips splash animation;
GRINTA_ACCESSIBLE=1 enables accessible mode (high-contrast, no animations, ASCII).
"""


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        '--model',
        '-m',
        help='Override LLM model (e.g. anthropic/claude-sonnet-4-6)',
    )
    parser.add_argument(
        '--project',
        '-p',
        type=_project_dir,
        help='Set project root directory',
    )
    parser.add_argument(
        '--no-splash',
        '--quiet',
        action='store_true',
        help='Start without the animated splash screen',
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Verbose mode: show detailed bootstrap and status information',
    )
    parser.add_argument(
        '--cleanup-storage',
        action='store_true',
        help='Consolidate legacy project data into the workspace storage root and exit',
    )
    parser.add_argument(
        '--minimal',
        action='store_true',
        help='Minimal mode: stripped borders and reduced HUD for cleaner display',
    )
    parser.add_argument(
        '--accessible',
        action='store_true',
        help='Accessible mode: high-contrast, no animations, ASCII symbols, simplified layout',
    )
    parser.add_argument(
        '--theme',
        choices=[
            'default',
            'dark',
            'ocean',
            'mono',
            'deep-system-instrumentation',
        ],
        default=None,
        help='Color theme preset (default: deep-system-instrumentation). Overrides GRINTA_THEME env var.',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {_version_string()}',
    )


def build_parser(*, include_subcommands: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='grinta',
        description='Grinta - AI coding agent for the terminal',
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_common_args(parser)
    if not include_subcommands:
        return parser

    subparsers = parser.add_subparsers(dest='subcommand')

    # `grinta init`
    p_init = subparsers.add_parser(
        'init', help='First-run wizard: pick provider, paste key, write settings.json'
    )
    p_init.add_argument(
        '--non-interactive',
        action='store_true',
        help='Write settings from env/flags without the wizard (for CI and scripts)',
    )
    p_init.add_argument(
        '--provider',
        help='LLM provider id (or set LLM_PROVIDER)',
    )
    p_init.add_argument(
        '--model',
        '-m',
        dest='init_model',
        help='Model id (or set LLM_MODEL)',
    )
    p_init.add_argument(
        '--base-url',
        help='OpenAI-compatible base URL (or set LLM_BASE_URL)',
    )
    p_init.add_argument(
        '--force',
        action='store_true',
        help='Overwrite an existing settings.json',
    )
    p_init.set_defaults(func=_run_init)

    p_doctor = subparsers.add_parser(
        'doctor',
        help='Run install, config, and toolchain diagnostics',
    )
    p_doctor.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Include slower checks (editing stack / tree-sitter)',
    )
    p_doctor.set_defaults(func=_run_doctor)

    # `grinta sessions ...`
    p_sessions = subparsers.add_parser('sessions', help='Manage past sessions')
    sessions_sub = p_sessions.add_subparsers(dest='sessions_cmd', required=True)

    p_list = sessions_sub.add_parser('list', help='List past sessions')
    p_list.add_argument('--limit', type=_positive_int, default=50)
    p_list.add_argument(
        '--search',
        '-s',
        dest='search',
        help='Filter sessions by fuzzy search on title/model',
    )

    p_show = sessions_sub.add_parser('show', help='Show one session')
    p_show.add_argument('target', help='Session index (1-based) or id prefix')

    p_export = sessions_sub.add_parser('export', help='Export a session')
    p_export.add_argument('target', help='Session index or id prefix')
    p_export.add_argument('out', help='Output directory or .zip path')

    p_delete = sessions_sub.add_parser('delete', help='Delete one session')
    p_delete.add_argument('target', help='Session index or id prefix')
    p_delete.add_argument('--yes', action='store_true', help='Skip confirmation')

    p_prune = sessions_sub.add_parser('prune', help='Delete sessions older than --days')
    p_prune.add_argument('--days', type=_non_negative_int, default=30)
    p_prune.add_argument('--yes', action='store_true', help='Skip confirmation')
    p_sessions.set_defaults(func=_run_sessions)
    return parser


def _version_string() -> str:
    try:
        from backend import get_version

        return get_version()
    except Exception:
        return 'unknown'


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('must be an integer') from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError('must be 1 or greater')
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('must be an integer') from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError('must be 0 or greater')
    return parsed


def _project_dir(value: str) -> str:
    from backend.core.workspace_resolution import resolve_existing_directory

    try:
        return str(resolve_existing_directory(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _pin_project(project: str | None) -> None:
    if not project:
        return
    os.environ['PROJECT_ROOT'] = str(Path(project).expanduser().resolve())


def _run_init(_args: argparse.Namespace) -> int:
    from backend.cli.main import _load_dotenv_early

    project = getattr(_args, 'project', None)
    _pin_project(project)
    _load_dotenv_early(explicit_project=project)

    non_interactive = bool(getattr(_args, 'non_interactive', False))
    if not sys.stdin.isatty() and not non_interactive:
        print(
            'grinta init is interactive. Run it in a terminal, pass '
            '`grinta init --non-interactive` with LLM_API_KEY / LLM_PROVIDER set, '
            'or create settings.json and .env manually under your Grinta settings root.',
            file=sys.stderr,
        )
        return 3

    if non_interactive or not sys.stdin.isatty():
        from rich.console import Console

        from backend.cli.onboarding.init_noninteractive import run_noninteractive_init
        from backend.cli.theme import no_color_enabled

        return run_noninteractive_init(
            project_root=Path(project) if project else None,
            provider=getattr(_args, 'provider', None),
            model=getattr(_args, 'init_model', None),
            base_url=getattr(_args, 'base_url', None),
            force=bool(getattr(_args, 'force', False)),
            console=Console(no_color=no_color_enabled()),
        )

    from rich.console import Console

    from backend.cli.onboarding.init_wizard import run_init
    from backend.cli.theme import no_color_enabled

    return run_init(
        project_root=Path(project) if project else None,
        console=Console(no_color=no_color_enabled()),
    )


def _run_doctor(args: argparse.Namespace) -> int:
    from rich.console import Console

    from backend.cli.doctor import cmd_doctor
    from backend.cli.main import _load_dotenv_early
    from backend.cli.theme import no_color_enabled

    _pin_project(getattr(args, 'project', None))
    _load_dotenv_early(explicit_project=getattr(args, 'project', None))
    console = Console(no_color=no_color_enabled(), legacy_windows=False)
    return cmd_doctor(console, verbose=bool(getattr(args, 'verbose', False)))


def _run_sessions(args: argparse.Namespace) -> int:
    from rich.console import Console

    from backend.cli.session import sessions_cli
    from backend.cli.theme import no_color_enabled

    _pin_project(getattr(args, 'project', None))
    console = Console(no_color=no_color_enabled())
    sub = args.sessions_cmd
    if sub == 'list':
        return sessions_cli.cmd_list(
            console, limit=args.limit, search=getattr(args, 'search', None)
        )
    if sub == 'show':
        return sessions_cli.cmd_show(console, args.target)
    if sub == 'export':
        return sessions_cli.cmd_export(console, args.target, args.out)
    if sub == 'delete':
        return sessions_cli.cmd_delete(console, args.target, yes=args.yes)
    if sub == 'prune':
        return sessions_cli.cmd_prune(console, days=args.days, yes=args.yes)
    print('Unknown sessions subcommand. Try `grinta sessions list`.', file=sys.stderr)
    return 2


def _ensure_linux_host_tools_early() -> None:
    try:
        from backend.utils.linux_host_tools import ensure_linux_host_tools

        ensure_linux_host_tools()
    except Exception:
        pass
    try:
        from backend.core.wsl import ensure_tmux_tmpdir

        ensure_tmux_tmpdir()
    except Exception:
        pass


def main() -> None:
    """Parse flags and launch the interactive REPL or a subcommand."""
    parser = build_parser(include_subcommands=True)

    args = parser.parse_args(sys.argv[1:])
    _ensure_linux_host_tools_early()

    # Subcommand dispatch.
    if args.subcommand == 'init':
        rc = _run_init(args) or 0
        sys.exit(int(rc))

    if args.subcommand == 'doctor':
        rc = _run_doctor(args) or 0
        sys.exit(int(rc))

    if args.subcommand == 'sessions':
        rc = _run_sessions(args) or 0
        sys.exit(int(rc))

    if args.subcommand is None:
        from backend.core.workspace_resolution import resolve_launch_project_directory

        _pin_project(str(resolve_launch_project_directory(args.project)))

    repl_main = importlib.import_module('backend.cli.main').main
    call_kwargs = {
        'model': args.model,
        'project': args.project,
        'cleanup_storage': args.cleanup_storage,
        'no_splash': args.no_splash,
    }
    if args.minimal:
        call_kwargs['minimal'] = True
    if args.accessible:
        call_kwargs['accessible'] = True
    if args.theme:
        call_kwargs['theme'] = args.theme
    if args.verbose:
        call_kwargs['verbose'] = True
    repl_main(**call_kwargs)


if __name__ == '__main__':
    main()
