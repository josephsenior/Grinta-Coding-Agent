"""File-card pending-queue helpers extracted from :class:`_AppRendererEventProcessorMixin`.

These three small helpers manage the per-path queues that pair an in-flight
file-action card with its corresponding observation card. They are kept
together because they are short, share the same queue lookup pattern, and
are only ever called from the event processor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.cli.tui._app_renderer_event_processor_mixin import (
        _AppRendererEventProcessorMixin,
    )


def _compact_file_card_path(_orch: '_AppRendererEventProcessorMixin', path: str) -> str:
    """Keep file tool card headlines to one compact row."""
    from backend.cli._event_renderer.text_utils import truncate_activity_detail

    return truncate_activity_detail(path or '?', 80)


def _remember_pending_file_card(
    orch: '_AppRendererEventProcessorMixin',
    attr: str,
    path: str,
    widget: Any,
) -> None:
    queues = getattr(orch, attr, None)
    if queues is None:
        return
    queues[(path or '').strip()].append(widget)


def _take_pending_file_card(
    orch: '_AppRendererEventProcessorMixin',
    attr: str,
    path: str,
) -> Any | None:
    queues = getattr(orch, attr, None)
    if queues is None:
        return None
    key = (path or '').strip()
    queue = queues.get(key)
    if not queue:
        return None
    widget = queue.popleft()
    if not queue:
        queues.pop(key, None)
    return widget


def _has_pending_file_card(
    orch: '_AppRendererEventProcessorMixin',
    attr: str,
    path: str,
) -> bool:
    queues = getattr(orch, attr, None)
    if queues is None:
        return False
    queue = queues.get((path or '').strip())
    return bool(queue)
