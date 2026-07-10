"""Helper utilities for building Grinta CLI argument parsers."""

from __future__ import annotations

import argparse


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add common arguments shared between CLI and headless modes."""
    parser.add_argument(
        '-t', '--task', type=str, default='', help='The task for the agent to perform'
    )
    parser.add_argument(
        '-f',
        '--file',
        type=str,
        help='Path to a file containing the task. Overrides -t if both are provided.',
    )
    parser.add_argument('-n', '--name', help='Session name', type=str, default='')
    parser.add_argument('--log-level', help='Set the log level', type=str, default=None)
    parser.add_argument(
        '-l',
        '--llm-config',
        default=None,
        type=str,
        help=(
            'Select an LLM config key already loaded into the app config (usually "llm"). '
            'Canonical settings are loaded from repo-root settings.json.'
        ),
    )
    parser.add_argument(
        '--agent-config',
        default=None,
        type=str,
        help=(
            'Select an agent key already loaded into app config (for example, "Orchestrator").'
        ),
    )
    parser.add_argument(
        '-v', '--version', action='store_true', help='Show version information'
    )


def add_headless_specific_arguments(parser: argparse.ArgumentParser) -> None:
    """Add arguments specific to headless mode (full evaluation suite)."""
    parser.add_argument(
        '-d', '--directory', type=str, help='The working directory for the agent'
    )
    parser.add_argument(
        '-c',
        '--agent-cls',
        default=None,
        type=str,
        help='Name of the default agent to use',
    )
    parser.add_argument(
        '-i',
        '--max-iterations',
        default=None,
        type=int,
        help='The maximum number of iterations to run the agent',
    )
    parser.add_argument(
        '-b',
        '--max-budget-per-task',
        type=float,
        help='The maximum budget allowed per task, beyond which the agent will stop.',
    )
    parser.add_argument(
        '--no-auto-continue',
        help=(
            'Disable auto-continue responses in headless mode (i.e. headless '
            'will read from stdin instead of auto-continuing)'
        ),
        action='store_true',
        default=False,
    )
    parser.add_argument(
        '--selected-repo',
        help='GitHub repository to clone (format: owner/repo)',
        type=str,
        default=None,
    )


def get_headless_parser() -> argparse.ArgumentParser:
    """Create argument parser for headless mode with full argument set."""
    parser = argparse.ArgumentParser(description='Run the agent via CLI')
    add_common_arguments(parser)
    add_headless_specific_arguments(parser)
    return parser
