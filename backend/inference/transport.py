"""Transport client protocol — refactor seam for SDK isolation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TransportBackend(Protocol):
    """Minimal completion surface implemented by direct SDK clients."""

    def completion(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any: ...

    async def acompletion(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any: ...
