"""Helper utilities for building Forge CLI argument parsers."""

from __future__ import annotations

import argparse
from argparse import ArgumentParser, _SubParsersAction

from backend.core.constants import DEFAULT_CONFIG_FILE


def get_subparser(parser: ArgumentParser, name: str) -> ArgumentParser:
    """Get a subparser by name from an argument parser.

    Args:
        parser: Parent argument parser
        name: Name of the subparser to retrieve

    Returns:
        The requested subparser

    Raises:
        ValueError: If subparser not found

    """
    for action in parser._actions:
        if isinstance(action, _SubParsersAction) and name in action.choices:
            return action.choices[name]
    msg = f"Subparser '{name}' not found"
    raise ValueError(msg)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """Add common arguments shared between CLI and headless modes."""
    parser.add_argument(
        "--config-file",
        type=str,
        default=DEFAULT_CONFIG_FILE,
        help=f"Path to the config file (default: {DEFAULT_CONFIG_FILE} in the current directory)",
    )
    parser.add_argument(
        "-t", "--task", type=str, default="", help="The task for the agent to perform"
    )
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        help="Path to a file containing the task. Overrides -t if both are provided.",
    )
    parser.add_argument("-n", "--name", help="Session name", type=str, default="")
    parser.add_argument("--log-level", help="Set the log level", type=str, default=None)
    parser.add_argument(
        "-l",
        "--llm-config",
        default=None,
        type=str,
        help='Replace default LLM ([llm] section in config.toml) config with the specified LLM config, e.g. "llama3" for [llm.llama3] section in config.toml',
    )
    parser.add_argument(
        "--agent-config",
        default=None,
        type=str,
        help='Replace default Agent ([agent] section in config.toml) config with the specified Agent config, e.g. "CodeAct" for [agent.CodeAct] section in config.toml',
    )
    parser.add_argument(
        "-v", "--version", action="store_true", help="Show version information"
    )


def add_headless_specific_arguments(parser: argparse.ArgumentParser) -> None:
    """Add arguments specific to headless mode (full evaluation suite)."""
    parser.add_argument(
        "-d", "--directory", type=str, help="The working directory for the agent"
    )
    parser.add_argument(
        "-c",
        "--agent-cls",
        default=None,
        type=str,
        help="Name of the default agent to use",
    )
    parser.add_argument(
        "-i",
        "--max-iterations",
        default=None,
        type=int,
        help="The maximum number of iterations to run the agent",
    )
    parser.add_argument(
        "-b",
        "--max-budget-per-task",
        type=float,
        help="The maximum budget allowed per task, beyond which the agent will stop.",
    )
    parser.add_argument(
        "--no-auto-continue",
        help="Disable auto-continue responses in headless mode (i.e. headless will read from stdin instead of auto-continuing)",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--selected-repo",
        help="GitHub repository to clone (format: owner/repo)",
        type=str,
        default=None,
    )


def get_cli_parser() -> argparse.ArgumentParser:
    """Create argument parser for Forge."""
    description = 'Welcome to Forge: Code Less, Make More\n\nForge is now a GUI-only application. Use "forge serve" to launch the web interface.'
    parser = argparse.ArgumentParser(
        description=description,
        prog="forge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        title="commands",
        metavar="COMMAND",
    )
    subparsers.add_parser("serve", help="Launch the Forge GUI server (web interface)")

    subparsers.add_parser(
        "health", help="Run production health checks for critical dependencies"
    )

    init_parser = subparsers.add_parser("init", help="Initialize a new Forge project")
    init_parser.add_argument(
        "project_name",
        nargs="?",
        help="Name of the project (defaults to current directory)",
    )
    init_parser.add_argument(
        "--template", default="basic", help="Project template to use"
    )

    parser.add_argument(
        "--conversation", help="The conversation id to continue", type=str, default=None
    )
    return parser


def get_headless_parser() -> argparse.ArgumentParser:
    """Create argument parser for headless mode with full argument set."""
    parser = argparse.ArgumentParser(description="Run the agent via CLI")
    add_common_arguments(parser)
    add_headless_specific_arguments(parser)
    return parser
