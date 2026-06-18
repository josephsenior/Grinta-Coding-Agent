"""Diagnostic helper — writes to the standard Python logger instead of a raw file."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def debug(msg: str) -> None:
    logger.debug(msg)
