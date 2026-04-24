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
    grinta --cleanup-storage         # Consolidate legacy storage into .grinta/storage
"""

from __future__ import annotations

import argparse
import importlib
import sys
import warnings

# Suppress ALL DeprecationWarnings before any package is imported.
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings(
    "ignore",
    message=r"Inheritance class AiohttpClientSession from ClientSession is discouraged",
    category=DeprecationWarning,
)


_EPILOG = """examples:
  grinta
      Start the interactive REPL in the current directory.
  grinta init
      Run the first-run wizard to configure your LLM provider.
  grinta sessions list
      List past sessions.
  grinta sessions prune --days 30 --yes
      Delete sessions older than 30 days, no prompt.
  grinta -p .
      Same, with an explicit project root (current directory).
  grinta -p /path/to/repo -m anthropic/claude-sonnet-4-20250514
      Use that project folder and override the model for this session only.
  grinta --cleanup-storage
      Consolidate legacy project data into .grinta/storage and exit.
"""


def _run_init(_args: argparse.Namespace) -> int:
    from rich.console import Console

    from backend.cli.init_wizard import run_init

    return run_init(console=Console())


def _run_sessions(args: argparse.Namespace) -> int:
    from rich.console import Console

    from backend.cli import sessions_cli

    console = Console()
    sub = args.sessions_cmd
    if sub == "list":
        return sessions_cli.cmd_list(console, limit=args.limit)
    if sub == "show":
        return sessions_cli.cmd_show(console, args.target)
    if sub == "export":
        return sessions_cli.cmd_export(console, args.target, args.out)
    if sub == "delete":
        return sessions_cli.cmd_delete(console, args.target, yes=args.yes)
    if sub == "prune":
        return sessions_cli.cmd_prune(console, days=args.days, yes=args.yes)
    print("Unknown sessions subcommand. Try `grinta sessions list`.", file=sys.stderr)
    return 2


def main() -> None:
    """Parse flags and launch the interactive REPL or a subcommand."""
    parser = argparse.ArgumentParser(
        prog="grinta",
        description="Grinta — AI coding agent for the terminal",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        "-m",
        help="Override LLM model (e.g. anthropic/claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--project",
        "-p",
        help="Set project root directory",
    )
    parser.add_argument(
        "--cleanup-storage",
        action="store_true",
        help="Consolidate legacy project data into .grinta/storage and exit",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    # `grinta init`
    p_init = subparsers.add_parser(
        "init", help="First-run wizard: pick provider, paste key, write settings.json"
    )
    p_init.set_defaults(func=_run_init)

    # `grinta sessions ...`
    p_sessions = subparsers.add_parser("sessions", help="Manage past sessions")
    sessions_sub = p_sessions.add_subparsers(dest="sessions_cmd")

    p_list = sessions_sub.add_parser("list", help="List past sessions")
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sessions_sub.add_parser("show", help="Show one session")
    p_show.add_argument("target", help="Session index (1-based) or id prefix")

    p_export = sessions_sub.add_parser("export", help="Export a session")
    p_export.add_argument("target", help="Session index or id prefix")
    p_export.add_argument("out", help="Output directory or .zip path")

    p_delete = sessions_sub.add_parser("delete", help="Delete one session")
    p_delete.add_argument("target", help="Session index or id prefix")
    p_delete.add_argument("--yes", action="store_true", help="Skip confirmation")

    p_prune = sessions_sub.add_parser("prune", help="Delete sessions older than --days")
    p_prune.add_argument("--days", type=int, default=30)
    p_prune.add_argument("--yes", action="store_true", help="Skip confirmation")

    p_sessions.set_defaults(func=_run_sessions)

    args = parser.parse_args(sys.argv[1:])

    # Subcommand dispatch.
    if getattr(args, "subcommand", None) is not None:
        func = getattr(args, "func", None)
        if func is None or not callable(func):
            parser.print_help()
            sys.exit(2)
        rc = func(args) or 0
        sys.exit(int(rc))

    repl_main = importlib.import_module("backend.cli.main").main
    repl_main(
        model=args.model,
        project=args.project,
        cleanup_storage=args.cleanup_storage,
    )


if __name__ == "__main__":
    main()
