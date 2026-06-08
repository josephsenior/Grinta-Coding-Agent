"""Shared types and module-level constants for the orchestrator executor.

Pure code motion: extracted from backend/engine/executor.py to break the
circular import between the slimmed main and the three new mixin files.
This file must not import any other executor submodule.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from backend.ledger.action import Action


@runtime_checkable
class ModelResponse(Protocol):
    """Structural type for LLM completion responses (OpenAI-compatible)."""

    choices: list
    id: str
    tool_calls: list[Any] | None  # OpenAI-style function/tool calls (optional)


_INLINE_OPEN_THINK_RE = re.compile(r'<(redacted_thinking|think)>', re.IGNORECASE)
_INLINE_CLOSE_THINK_RE = re.compile(r'</(redacted_thinking|think)>', re.IGNORECASE)

_MAX_CHECKPOINT_CACHE_SIZE = 16


@dataclass(slots=True)
class ExecutionResult:
    """Container for executor outcomes."""

    actions: list[Action] = field(default_factory=list)
    response: ModelResponse | Any | None = None
    execution_time: float = 0.0
    error: str | None = None


@dataclass(slots=True)
class _AsyncStreamingState:
    content_accumulate: str = ''
    thinking_accumulate: str = ''
    tool_calls_dict: dict[int, dict[str, Any]] = field(default_factory=dict)
    streamed_usage: dict[str, int] | None = None
    in_inline_think_block: bool = False
    last_text_emit_at: float = 0.0
    last_text_emit_len: int = 0
    last_thinking_emit_at: float = 0.0
    last_thinking_emit_len: int = 0


class _FunctionCallingProxy:
    """Proxy that forwards attribute access to the live function_calling module.

    Keeps track of attribute overrides (via monkeypatch) so they persist even if
    the underlying module is reloaded during other tests.
    """

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self._overrides: dict[str, Any] = {}

    @property
    def module(self):
        return sys.modules[self.module_name]

    def __getattr__(self, item):
        if item in self._overrides:
            return self._overrides[item]
        return getattr(self.module, item)

    def __setattr__(self, key, value):
        if key in {'module_name', '_overrides'}:
            object.__setattr__(self, key, value)
        else:
            self._overrides[key] = value
            setattr(self.module, key, value)


orchestrator_function_calling = _FunctionCallingProxy('backend.engine.function_calling')
