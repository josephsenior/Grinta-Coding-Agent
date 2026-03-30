"""Runtime supervisor.

Centralizes runtime lifecycle (connect/close) ownership and readiness waiting.
This reduces ad-hoc background loops scattered across the server layer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from backend.core.logger import app_logger as logger


@dataclass(frozen=True, slots=True)
class RuntimeSupervisorConfig:
    connect_timeout_s: float = 30.0
    readiness_timeout_s: float = 5.0
    readiness_poll_s: float = 0.1


class RuntimeSupervisor:
    def __init__(self, config: RuntimeSupervisorConfig | None = None) -> None:
        self._config = config or RuntimeSupervisorConfig()

    async def ensure_connected(self, conversation: object) -> None:
        """Connect a conversation runtime and wait for readiness if supported."""
        runtime = getattr(conversation, "runtime", None)
        if runtime is None:
            return

        connect_coro = getattr(runtime, "connect", None)
        if connect_coro is None:
            return

        try:
            await asyncio.wait_for(
                connect_coro(), timeout=self._config.connect_timeout_s
            )
        except TimeoutError:
            logger.warning(
                "Runtime connect timed out after %.1fs for sid=%s",
                self._config.connect_timeout_s,
                getattr(conversation, "sid", ""),
            )
            return
        except Exception as exc:
            logger.error(
                "Runtime connect failed for sid=%s: %s",
                getattr(conversation, "sid", ""),
                exc,
                exc_info=True,
            )
            return

        await self._wait_for_readiness(runtime, getattr(conversation, "sid", ""))

    async def close(self, conversation: object) -> None:
        runtime = getattr(conversation, "runtime", None)
        if runtime is None:
            return
        close_fn = getattr(runtime, "close", None)
        if close_fn is None:
            return
        try:
            result = close_fn()
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.debug(
                "Runtime close failed for sid=%s: %s",
                getattr(conversation, "sid", ""),
                exc,
            )

    async def _wait_for_readiness(self, runtime: object, sid: str) -> None:
        if not hasattr(runtime, "runtime_initialized"):
            return
        try:
            if getattr(runtime, "runtime_initialized"):
                return
        except Exception:
            return

        deadline = self._config.readiness_timeout_s
        waited = 0.0
        while waited < deadline:
            try:
                if getattr(runtime, "runtime_initialized"):
                    return
            except Exception:
                return
            await asyncio.sleep(self._config.readiness_poll_s)
            waited += self._config.readiness_poll_s

        logger.warning(
            "Runtime for conversation %s did not initialize within %.1fs",
            sid,
            self._config.readiness_timeout_s,
        )


runtime_supervisor = RuntimeSupervisor()
