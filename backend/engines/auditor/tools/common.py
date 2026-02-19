"""Common tool parameter definitions for Auditor tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.engines.common import (
    create_tool_definition,
    get_common_path_param,
    get_common_pattern_param,
)

if TYPE_CHECKING:
    pass

__all__ = [
    "create_tool_definition",
    "get_common_path_param",
    "get_common_pattern_param",
]
