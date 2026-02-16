"""Common tool parameter definitions for Auditor tools."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from backend.engines.common import (
    create_tool_definition,
    get_common_path_param,
    get_common_pattern_param,
)

if TYPE_CHECKING:
    from backend.engines.orchestrator.contracts import ChatCompletionToolParam

__all__ = [
    "create_tool_definition",
    "get_common_path_param",
    "get_common_pattern_param",
]

