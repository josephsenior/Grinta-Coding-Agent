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
  grinta --project /path/to/repo sessions list
      List sessions for an explicit project root.
  grinta sessions list
      List past sessions.
  grinta sessions prune --days 30 --yes
      Delete sessions older than 30 days, no prompt.
  grinta -p .
      Same, with an explicit project root (current directory).
  grinta -p /path/to/repo -m anthropic/claude-sonnet-4-20250514
      Use that project folder and override the model for this session only.
  grinta --cleanup-storage
      Consolidate legacy project data into the canonical workspace store and exit.
"""


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
    from rich.console import Console

    from backend.cli.init_wizard import run_init

    project = getattr(_args, 'project', None)
    _pin_project(project)
    return run_init(project_root=Path(project) if project else None, console=Console())


def _run_sessions(args: argparse.Namespace) -> int:
    from rich.console import Console

    from backend.cli import sessions_cli

    _pin_project(getattr(args, 'project', None))
    console = Console()
    sub = args.sessions_cmd
    if sub == 'list':
        return sessions_cli.cmd_list(console, limit=args.limit)
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


def main() -> None:
    """Parse flags and launch the interactive REPL or a subcommand."""
    parser = argparse.ArgumentParser(
        prog='grinta',
        description='Grinta — AI coding agent for the terminal',
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--model',
        '-m',
        help='Override LLM model (e.g. anthropic/claude-sonnet-4-20250514)',
    )
    parser.add_argument(
        '--project',
        '-p',
        type=_project_dir,
        help='Set project root directory',
    )
    parser.add_argument(
        '--no-splash',
        action='store_true',
        help='Start without the animated splash screen',
    )
    parser.add_argument(
        '--cleanup-storage',
        action='store_true',
        help='Consolidate legacy project data into the canonical workspace store and exit',
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {_version_string()}',
    )

    subparsers = parser.add_subparsers(dest='subcommand')

    # `grinta init`
    p_init = subparsers.add_parser(
        'init', help='First-run wizard: pick provider, paste key, write settings.json'
    )
    p_init.set_defaults(func=_run_init)

    # `grinta sessions ...`
    p_sessions = subparsers.add_parser('sessions', help='Manage past sessions')
    sessions_sub = p_sessions.add_subparsers(dest='sessions_cmd', required=True)

    p_list = sessions_sub.add_parser('list', help='List past sessions')
    p_list.add_argument('--limit', type=_positive_int, default=50)

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

    args = parser.parse_args(sys.argv[1:])

    # Subcommand dispatch.
    if args.subcommand == 'init':
        rc = _run_init(args) or 0
        sys.exit(int(rc))

    if args.subcommand == 'sessions':
        rc = _run_sessions(args) or 0
        sys.exit(int(rc))

    repl_main = importlib.import_module('backend.cli.main').main
    repl_main(
        model=args.model,
        project=args.project,
        cleanup_storage=args.cleanup_storage,
        no_splash=args.no_splash,
    )


if __name__ == '__main__':
    main()
