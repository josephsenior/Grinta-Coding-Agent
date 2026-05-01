"""Observation for native browser JPEG screenshots (multimodal-capable)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.schemas import ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class BrowserScreenshotObservation(Observation):
    """Screenshot saved to disk with optional base64 payload for vision models."""

    image_path: str = ''
    image_b64: str = ''
    image_mime: str = 'image/jpeg'
    width: int | None = None
    height: int | None = None
    command: str = 'browser screenshot'
    inject_skipped_reason: str | None = None

    observation: ClassVar[str] = ObservationType.BROWSER_SCREENSHOT

    def __init__(
        self,
        content: str,
        *,
        image_path: str = '',
        image_b64: str = '',
        image_mime: str = 'image/jpeg',
        width: int | None = None,
        height: int | None = None,
        command: str = 'browser screenshot',
        inject_skipped_reason: str | None = None,
    ) -> None:
        """Initialize with ``content`` as the human-readable caption (path + size)."""
        super().__init__(content)
        self.image_path = image_path
        self.image_b64 = image_b64
        self.image_mime = image_mime
        self.width = width
        self.height = height
        self.command = command
        self.inject_skipped_reason = inject_skipped_reason
