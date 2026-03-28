"""Convenience exports for Forge input/output helper functions."""

from backend.gateway.adapters.cli_input import read_input, read_task, read_task_from_file
from backend.gateway.adapters.json import dumps, loads

__all__ = ["dumps", "loads", "read_input", "read_task", "read_task_from_file"]
