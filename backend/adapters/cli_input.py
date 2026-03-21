"""Command-line helpers for reading tasks and interactive input."""

import argparse
import sys


def read_input(cli_multiline_input: bool = False) -> str:
    """Read input from user based on config settings."""
    if not cli_multiline_input:
        return input(">> ").rstrip()
    lines = []
    while True:
        line = input(">> ").rstrip()
        if line == "/exit":
            break
        lines.append(line)
    return "\n".join(lines)


def read_task_from_file(file_path: str) -> str:
    """Read task from the specified file."""
    with open(file_path, encoding="utf-8") as file:
        return file.read()


def read_task(args: argparse.Namespace, cli_multiline_input: bool) -> str:
    """Read the task from the CLI args, file, or stdin."""
    task_str = ""
    if args.file:
        task_str = read_task_from_file(args.file)
    elif args.task:
        task_str = args.task
    elif not sys.stdin.isatty():
        task_str = read_input(cli_multiline_input)
    return task_str
