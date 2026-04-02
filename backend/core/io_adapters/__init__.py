"""Convenience exports for CLI input/output helper functions.

Relocated from ``backend.gateway.adapters`` during gateway removal.
"""

from backend.core.io_adapters.cli_input import (
    read_input,
    read_task,
    read_task_from_file,
)
from backend.core.io_adapters.json import dumps, loads

__all__ = ['dumps', 'loads', 'read_input', 'read_task', 'read_task_from_file']
