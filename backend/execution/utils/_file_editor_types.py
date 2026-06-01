"""Shared types for FileEditor mixin modules.

Pure code motion: split from ``backend.execution.utils.file_editor`` to
break circular imports between sibling mixin modules. No logic changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any



@dataclass
class ToolResult:
    """Result of a file editor operation."""

    output: str
    error: str | None = None
    old_content: str | None = None
    new_content: str | None = None
    error_code: str | None = None
    retryable: bool = False
    operation: str | None = None
    metadata: dict[str, Any] | None = None

