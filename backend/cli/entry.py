"""Unified CLI entry point for the ``app`` console script.

Subcommands::

    app             # Launch interactive REPL (default)
    app serve       # Start the backend API server
    app start       # Alias for serve
    app all         # Alias for serve

REPL flags::

    app --model anthropic/claude-sonnet-4-20250514
    app --project /path/to/repo
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Dispatch to the appropriate mode based on the first positional arg."""
    subcommand = sys.argv[1] if len(sys.argv) > 1 else None

    if subcommand in ("serve", "start", "all"):
        # Strip the subcommand so embedded's argparse sees only flags.
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from backend.embedded import main as serve_main

        serve_main()
        return

    # REPL mode — parse optional flags.
    parser = argparse.ArgumentParser(
        prog="app",
        description="Grinta interactive CLI",
        epilog="Subcommands: 'app serve|start|all' starts the backend API server.",
    )
    parser.add_argument(
        "--model", "-m",
        help="Override LLM model (e.g. anthropic/claude-sonnet-4-20250514)",
    )
    parser.add_argument(
        "--project", "-p",
        help="Set project root directory",
    )
    args = parser.parse_args()

    from backend.cli.main import main as repl_main

    repl_main(model=args.model, project=args.project)


if __name__ == "__main__":
    main()
