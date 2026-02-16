from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class FunctionChunkArgs(TypedDict):
    name: str
    description: NotRequired[str]
    parameters: NotRequired[dict[str, Any]]
    strict: NotRequired[bool]


def make_function_chunk(**chunk_kwargs: Any) -> Any:
    """Create a function chunk dict fallback.

    The result supports both dict-style and attribute-style access,
    matching tests and production code expectations.
    """

    class _Chunk(dict):  # attribute-friendly dict
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError as exc:
                raise AttributeError(key) from exc

        def __setattr__(self, key, value):
            self[key] = value

    return _Chunk(dict(chunk_kwargs.items()))


def make_tool_param(function: Any, type: str = "function", **extras: Any) -> Any:
    """Create a tool param dict fallback.

    Keeps interface consistent during tests.
    """

    class _Tool(dict):  # attribute-friendly dict
        def __getattr__(self, key):
            try:
                return self[key]
            except KeyError as exc:
                raise AttributeError(key) from exc

        def __setattr__(self, key, value):
            self[key] = value

    payload = {"type": type, "function": function}
    payload.update(extras)
    return _Tool(payload)


class PromptTokensDetails:
    def __init__(self, cached_tokens: int | None = None, **kwargs: Any):
        self.cached_tokens = cached_tokens


__all__ = [
    "FunctionChunkArgs",
    "make_function_chunk",
    "make_tool_param",
    "PromptTokensDetails",
]
