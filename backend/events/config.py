"""Event subsystem configuration accessors."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class EventRuntimeDefaults:
    max_queue_size: int = 2000
    drop_policy: str = "drop_oldest"
    hwm_ratio: float = 0.8
    block_timeout: float = 0.1
    rate_window_seconds: int = 60
    workers: int = 8
    async_write: bool = False
    coalesce: bool = False
    coalesce_window_ms: float = 100.0
    coalesce_max_batch: int = 20


@lru_cache(maxsize=1)
def get_event_runtime_defaults() -> EventRuntimeDefaults:
    """Resolve event runtime defaults from Forge config, then env fallback."""
    try:
        from backend.core.config.utils import load_FORGE_config

        cfg = load_FORGE_config()
        event_cfg = getattr(cfg, "event_stream", None)
        if event_cfg is not None:
            return EventRuntimeDefaults(
                max_queue_size=int(getattr(event_cfg, "max_queue_size", 2000)),
                drop_policy=str(getattr(event_cfg, "drop_policy", "drop_oldest")),
                hwm_ratio=float(getattr(event_cfg, "hwm_ratio", 0.8)),
                block_timeout=float(getattr(event_cfg, "block_timeout", 0.1)),
                rate_window_seconds=int(getattr(event_cfg, "rate_window_seconds", 60)),
                workers=max(1, int(getattr(event_cfg, "workers", 8))),
                async_write=bool(getattr(event_cfg, "async_write", False)),
                coalesce=bool(getattr(event_cfg, "coalesce", False)),
                coalesce_window_ms=float(
                    getattr(event_cfg, "coalesce_window_ms", 100.0)
                ),
                coalesce_max_batch=max(
                    1,
                    int(getattr(event_cfg, "coalesce_max_batch", 20)),
                ),
            )
    except Exception:
        pass

    return EventRuntimeDefaults(
        max_queue_size=int(os.getenv("FORGE_EVENTSTREAM_MAX_QUEUE", "2000")),
        drop_policy=os.getenv("FORGE_EVENTSTREAM_POLICY", "drop_oldest").lower(),
        hwm_ratio=float(os.getenv("FORGE_EVENTSTREAM_HWM_RATIO", "0.8")),
        block_timeout=float(os.getenv("FORGE_EVENTSTREAM_BLOCK_TIMEOUT", "0.1")),
        rate_window_seconds=int(
            os.getenv("FORGE_EVENTSTREAM_RATE_WINDOW_SECONDS", "60")
        ),
        workers=max(1, int(os.getenv("FORGE_EVENTSTREAM_WORKERS", "8"))),
        async_write=os.getenv("FORGE_EVENTSTREAM_ASYNC_WRITE", "false").lower()
        in ("1", "true", "yes"),
        coalesce=os.getenv("FORGE_EVENT_COALESCE", "false").lower()
        in ("1", "true", "yes"),
        coalesce_window_ms=float(os.getenv("FORGE_EVENT_COALESCE_WINDOW_MS", "100")),
        coalesce_max_batch=max(
            1,
            int(os.getenv("FORGE_EVENT_COALESCE_MAX_BATCH", "20")),
        ),
    )
