"""Event subsystem configuration accessors."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _get_env(*names: str, default: str) -> str:
    """Read first non-empty value from preferred env names."""
    for name in names:
        value = os.getenv(name)
        if value is not None and value != '':
            return value
    return default


@dataclass(frozen=True)
class EventRuntimeDefaults:
    max_queue_size: int = 2000
    drop_policy: str = 'drop_oldest'
    hwm_ratio: float = 0.8
    block_timeout: float = 0.1
    rate_window_seconds: int = 60
    # Single worker preserves FIFO delivery to WebSocket subscribers. With >1,
    # parallel dispatch can reorder events (e.g. final MESSAGE before earlier
    # STREAMING_CHUNK), and the UI drops "stale" ids — so streaming looks instant.
    workers: int = 1
    async_write: bool = False
    coalesce: bool = False
    coalesce_window_ms: float = 100.0
    coalesce_max_batch: int = 20


@lru_cache(maxsize=1)
def get_event_runtime_defaults() -> EventRuntimeDefaults:
    """Resolve event runtime defaults from app config, then env fallback."""
    try:
        from backend.core.config.config_loader import load_app_config

        cfg = load_app_config()
        event_cfg = getattr(cfg, 'event_stream', None)
        if event_cfg is not None:
            return EventRuntimeDefaults(
                max_queue_size=int(getattr(event_cfg, 'max_queue_size', 2000)),
                drop_policy=str(getattr(event_cfg, 'drop_policy', 'drop_oldest')),
                hwm_ratio=float(getattr(event_cfg, 'hwm_ratio', 0.8)),
                block_timeout=float(getattr(event_cfg, 'block_timeout', 0.1)),
                rate_window_seconds=int(getattr(event_cfg, 'rate_window_seconds', 60)),
                workers=max(1, int(getattr(event_cfg, 'workers', 1))),
                async_write=bool(getattr(event_cfg, 'async_write', False)),
                coalesce=bool(getattr(event_cfg, 'coalesce', False)),
                coalesce_window_ms=float(
                    getattr(event_cfg, 'coalesce_window_ms', 100.0)
                ),
                coalesce_max_batch=max(
                    1,
                    int(getattr(event_cfg, 'coalesce_max_batch', 20)),
                ),
            )
    except Exception:
        pass

    return EventRuntimeDefaults(
        max_queue_size=int(
            _get_env(
                'EVENT_STREAM_MAX_QUEUE_SIZE',
                'APP_EVENTSTREAM_MAX_QUEUE',
                default='2000',
            )
        ),
        drop_policy=_get_env(
            'EVENT_STREAM_DROP_POLICY', 'APP_EVENTSTREAM_POLICY', default='drop_oldest'
        ).lower(),
        hwm_ratio=float(
            _get_env(
                'EVENT_STREAM_HWM_RATIO', 'APP_EVENTSTREAM_HWM_RATIO', default='0.8'
            )
        ),
        block_timeout=float(
            _get_env(
                'EVENT_STREAM_BLOCK_TIMEOUT',
                'APP_EVENTSTREAM_BLOCK_TIMEOUT',
                default='0.1',
            )
        ),
        rate_window_seconds=int(
            _get_env(
                'EVENT_STREAM_RATE_WINDOW_SECONDS',
                'APP_EVENTSTREAM_RATE_WINDOW_SECONDS',
                default='60',
            )
        ),
        workers=max(
            1,
            int(
                _get_env('EVENT_STREAM_WORKERS', 'APP_EVENTSTREAM_WORKERS', default='1')
            ),
        ),
        async_write=_get_env(
            'EVENT_STREAM_ASYNC_WRITE',
            'APP_EVENTSTREAM_ASYNC_WRITE',
            default='false',
        ).lower()
        in ('1', 'true', 'yes'),
        coalesce=_get_env(
            'EVENT_STREAM_COALESCE',
            'APP_EVENT_COALESCE',
            default='false',
        ).lower()
        in ('1', 'true', 'yes'),
        coalesce_window_ms=float(
            _get_env(
                'EVENT_STREAM_COALESCE_WINDOW_MS',
                'APP_EVENT_COALESCE_WINDOW_MS',
                default='100',
            )
        ),
        coalesce_max_batch=max(
            1,
            int(
                _get_env(
                    'EVENT_STREAM_COALESCE_MAX_BATCH',
                    'APP_EVENT_COALESCE_MAX_BATCH',
                    default='20',
                )
            ),
        ),
    )
