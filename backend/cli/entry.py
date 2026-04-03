"""Unified CLI entry point for the ``grinta`` console script.

Usage::

    grinta                           # Launch interactive REPL
    grinta --model anthropic/...     # Override model
    grinta --project /path/to/repo   # Set project root
"""

from __future__ import annotations

import argparse
import os
import sys
import warnings

# Suppress ALL DeprecationWarnings before any package is imported.
warnings.filterwarnings('ignore', category=DeprecationWarning)


def main() -> None:
    """Parse flags and launch the interactive REPL."""
    # Mark CLI mode before ANY backend imports so backend/core/logger.py
    # skips its stdout handlers when it's imported for the first time.
    os.environ.setdefault('AGENT_CLI_MODE', 'true')

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
    args = parser.parse_args(sys.argv[1:])

    from backend.cli.main import main as repl_main

    repl_main(model=args.model, project=args.project)


if __name__ == '__main__':
    main()
