"""Session state debug endpoint for live introspection.

Exposes internal session diagnostics: controller state, memory pressure,
rate governor stats, circuit breaker status, replay state, and event
stream metrics.  Only enabled when ``FORGE_DEBUG=true`` or in development.

Endpoint: ``GET /api/debug/session/{session_id}``
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend.core.logger import forge_logger as logger

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])

_DEBUG_ENABLED = os.getenv("FORGE_DEBUG", "false").lower() in ("true", "1", "yes")


def _collect_controller_snapshot(controller: Any) -> dict[str, Any]:
    """Extract metrics from the agent controller."""
    info: dict[str, Any] = {}
    state = getattr(controller, "state", None)
    if state:
        info["state"] = {
            "agent_state": str(getattr(state, "agent_state", "?")),
            "iteration": getattr(
                getattr(state, "iteration_flag", None), "current_value", None
            ),
            "max_iterations": getattr(state, "max_iterations", None),
            "last_error": getattr(state, "last_error", None),
        }
        metrics = getattr(state, "metrics", None)
        if metrics:
            usage = getattr(metrics, "accumulated_token_usage", None)
            if usage:
                info["token_usage"] = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total": getattr(usage, "prompt_tokens", 0)
                    + getattr(usage, "completion_tokens", 0),
                }
    return info


def _collect_event_stream_debug(event_stream: Any) -> dict[str, Any]:
    """Capture event stream health metrics."""
    info: dict[str, Any] = {
        "event_count": len(event_stream) if hasattr(event_stream, "__len__") else "?",
    }
    bp = getattr(event_stream, "_backpressure", None)
    if bp and hasattr(bp, "snapshot"):
        info["backpressure"] = bp.snapshot()
    return info


def _collect_session_snapshot(controller: Any, session_id: str) -> dict[str, Any]:
    """Build diagnostic snapshot from controller."""
    snapshot: dict[str, Any] = {"session_id": session_id, "status": "active"}
    snapshot.update(_collect_controller_snapshot(controller))

    rate_gov = getattr(controller, "rate_governor", None)
    if rate_gov and hasattr(rate_gov, "snapshot"):
        snapshot["rate_governor"] = rate_gov.snapshot()

    mem_pressure = getattr(controller, "memory_pressure", None)
    if mem_pressure and hasattr(mem_pressure, "snapshot"):
        snapshot["memory_pressure"] = mem_pressure.snapshot()

    with contextlib.suppress(Exception):
        from backend.utils.circuit_breaker import get_circuit_breaker_metrics_snapshot
        snapshot["circuit_breaker"] = get_circuit_breaker_metrics_snapshot()

    replay = getattr(controller, "_replay_manager", None)
    if replay and hasattr(replay, "snapshot"):
        snapshot["replay"] = replay.snapshot()

    event_stream = getattr(controller, "event_stream", None)
    if event_stream:
        snapshot["event_stream"] = _collect_event_stream_debug(event_stream)

    agent = getattr(controller, "agent", None)
    if agent:
        llm_lat = getattr(agent, "_last_llm_latency", None)
        if llm_lat:
            snapshot["last_llm_latency_s"] = round(llm_lat, 3)

    return snapshot


@router.get("/session/{session_id}")
async def session_debug(session_id: str) -> JSONResponse:
    """Return a diagnostic snapshot of a live session."""
    if not _DEBUG_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Debug endpoint disabled. Set FORGE_DEBUG=true to enable.",
        )

    try:
        from backend.gateway.session.manager import session_manager

        session = session_manager.get_session(session_id)
        if session is None:
            raise HTTPException(
                status_code=404, detail=f"Session {session_id} not found"
            )

        controller = getattr(session, "controller", None)
        if controller is None:
            return JSONResponse({"session_id": session_id, "status": "no_controller"})

        snapshot = _collect_session_snapshot(controller, session_id)
        return JSONResponse(snapshot)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Debug endpoint error for session %s", session_id)
        return JSONResponse(
            {"session_id": session_id, "error": str(e)},
            status_code=500,
        )


@router.get("/sessions")
async def list_debug_sessions() -> JSONResponse:
    """List all active session IDs (debug only)."""
    if not _DEBUG_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="Debug endpoint disabled. Set FORGE_DEBUG=true to enable.",
        )

    try:
        from backend.gateway.session.manager import session_manager

        sessions = session_manager.list_sessions()
        return JSONResponse({"sessions": sessions})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
