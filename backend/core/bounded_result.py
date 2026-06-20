"""Shared I/O types used across backend layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BoundedResult:
    """Outcome of a bounded subprocess read."""

    stdout: str
    stderr: str
    returncode: int
    truncated: bool
    timed_out: bool
