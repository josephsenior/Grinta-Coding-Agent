"""Invalidate symbol-index entries after mutating file edits."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logging.logger import app_logger as logger
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.tool_pipeline import ToolInvocationContext


class SymbolIndexInvalidationMiddleware(ToolInvocationMiddleware):
    """Drop cached index rows for paths touched by successful file edits."""

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        try:
            from backend.ledger.observation import ErrorObservation
            from backend.ledger.observation.files import FileEditObservation

            if isinstance(observation, ErrorObservation):
                return
            if not isinstance(observation, FileEditObservation):
                return

            path = str(getattr(observation, 'path', '') or '').strip()
            if not path:
                return

            config = getattr(getattr(ctx, 'controller', None), 'config', None)
            from backend.context.symbol_index.store import (
                get_symbol_index_store,
                symbol_index_enabled,
            )

            if not symbol_index_enabled(config):
                return
            store = get_symbol_index_store()
            if store is None:
                return
            store.invalidate_path(path)
        except Exception:
            logger.debug('Symbol index invalidation skipped', exc_info=True)


__all__ = ['SymbolIndexInvalidationMiddleware']
