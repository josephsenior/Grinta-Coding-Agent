"""Unified CLI entry point for the ``grinta`` console script.

Usage::

    grinta                           # Launch interactive REPL
    grinta --model anthropic/...     # Override model
    grinta --project /path/to/repo   # Set project root
    grinta --cleanup-storage         # Consolidate legacy storage into .grinta/storage
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import warnings

# Suppress ALL DeprecationWarnings before any package is imported.
warnings.filterwarnings('ignore', category=DeprecationWarning)


def main() -> None:
    """Parse flags and launch the interactive REPL."""
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
        help='Consolidate legacy project data into .grinta/storage and exit',
    )
    args = parser.parse_args(sys.argv[1:])

    repl_main = getattr(importlib.import_module('backend.cli.main'), 'main')
    repl_main(
        model=args.model,
        project=args.project,
        cleanup_storage=args.cleanup_storage,
    )


if __name__ == '__main__':
    main()
