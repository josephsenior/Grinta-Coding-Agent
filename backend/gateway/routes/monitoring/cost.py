"""Cost summary routes for monitoring."""

from typing import Any

from fastapi import APIRouter, HTTPException

from . import monitoring_helpers

router = APIRouter()


def _extract_cost_from_session(sid: str, session: Any) -> tuple[dict[str, Any], float] | None:
    """Extract cost summary from session. Returns (entry, raw_cost) or None."""
    controller = getattr(session, "controller", None)
    if controller is None:
        return None
    state = getattr(controller, "state", None)
    metrics = getattr(state, "metrics", None) if state else None
    if metrics is None:
        return None
    cost = getattr(metrics, "accumulated_cost", 0.0)
    budget = getattr(metrics, "max_budget_per_task", None)
    pct = round(cost / budget, 4) if budget and budget > 0 else None
    entry = {
        "session_id": sid,
        "accumulated_cost_usd": round(cost, 6),
        "budget_limit_usd": budget,
        "pct_used": pct,
    }
    return entry, cost


def _collect_cost_sessions(manager: Any) -> tuple[list[dict[str, Any]], float]:
    """Collect cost data from all sessions. Returns (sessions, total_cost)."""
    convos = monitoring_helpers.get_conversation_sessions(manager) if manager else {}
    sessions: list[dict[str, Any]] = []
    total_cost = 0.0
    for sid, session in convos.items():
        result = _extract_cost_from_session(sid, session)
        if result:
            entry, cost = result
            total_cost += cost
            sessions.append(entry)
    return sessions, total_cost


@router.get("/cost-summary")
async def get_cost_summary():
    """Per-session cost and budget summary for all active conversations.

    Returns accumulated cost, budget limit, percentage used, and a
    list of per-session cost breakdowns.  Useful for dashboards and
    preventing surprise bills.
    """
    try:
        manager = monitoring_helpers.get_manager()
        sessions, total_cost = _collect_cost_sessions(manager)
        return {
            "total_cost_usd": round(total_cost, 6),
            "active_sessions": len(sessions),
            "sessions": sessions,
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e)) from e
