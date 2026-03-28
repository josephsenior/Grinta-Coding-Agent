"""Semantic condenser implementation.

This module intentionally stays dependency-free. It provides a lightweight
importance scoring heuristic and selection logic for keeping a compact view
of the event history.

Unit tests rely on the public API surface here (EventImportance + helper
methods), so keep this stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.ledger.action import Action, MessageAction
from backend.ledger.action.agent import CondensationAction
from backend.ledger.observation import Observation
from backend.context.condenser.condenser import BaseLLMCondenser, Condensation
from backend.context.view import View

if TYPE_CHECKING:
    from backend.ledger.event import Event

# (keywords, attr, score, reason) for _score_action_event
_ACTION_SCORE_RULES: list[tuple[tuple[str, ...], str, float, str]] = [
    (("file",), "action", 0.4, "file_operation"),
    (("delegate",), "action", 0.4, "delegation"),
    (("finish", "complete"), "action", 0.4, "completion"),
    (("install", "pip", "npm", "yarn", "uv", "conda"), "command", 0.3, "setup_command"),
]


@dataclass
class EventImportance:
    event: Event
    importance_score: float
    reasons: list[str] = field(default_factory=list)


class SemanticCondenser(BaseLLMCondenser):
    """Heuristic condenser that keeps important and coherent history slices."""

    def __init__(
        self,
        llm: Any = None,
        *,
        max_size: int = 100,
        keep_first: int = 5,
        max_event_length: int = 10000,
        importance_threshold: float = 0.5,
        # Back-compat with older config fields (ignored by this implementation)
        similarity_threshold: float | None = None,
        model_name: str | None = None,
        token_budget: int | None = None,
    ) -> None:
        super().__init__(llm, max_size=max_size, keep_first=keep_first, max_event_length=max_event_length)
        self.importance_threshold = importance_threshold
        self.similarity_threshold = similarity_threshold
        self.model_name = model_name
        self.token_budget = token_budget

    @staticmethod
    def _get_extra_config_args(config: Any) -> dict[str, Any]:
        args = BaseLLMCondenser._get_extra_config_args(config)
        # Accept optional fields if present; they are ignored by the heuristic condenser.
        for key in ("similarity_threshold", "model_name", "token_budget", "importance_threshold"):
            if hasattr(config, key):
                args[key] = getattr(config, key)
        return args

    # ------------------------------------------------------------------
    # Scoring helpers (unit-test visible)
    # ------------------------------------------------------------------

    def _score_action_event(self, event: Action) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        action_name = str(getattr(event, "action", "") or "").lower()
        command = str(getattr(event, "command", "") or "").lower()
        text_by_attr: dict[str, str] = {"action": action_name, "command": command}

        for keywords, attr, inc, reason in _ACTION_SCORE_RULES:
            text = text_by_attr.get(attr, "")
            if text and any(kw in text for kw in keywords):
                score += inc
                reasons.append(reason)
        return score, reasons

    def _score_observation_event(self, event: Observation) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        error = getattr(event, "error", None)
        if error:
            score += 0.6
            reasons.append("error")
        else:
            exit_code = getattr(event, "exit_code", None)
            if exit_code == 0:
                score += 0.2
                reasons.append("success")

        content = getattr(event, "content", None)
        if isinstance(content, str) and len(content) >= 1000:
            score += 0.2
            reasons.append("detailed_output")

        return score, reasons

    def _score_message_event(self, event: MessageAction) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        source = str(getattr(event, "source", "") or "").lower()
        if source == "user":
            score += 0.4
            reasons.append("user_message")

        content = getattr(event, "content", None)
        if isinstance(content, str) and "?" in content:
            score += 0.2
            reasons.append("question")

        return score, reasons

    def _calculate_importance(self, event: Event) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        # Detect message-like events first (MessageAction is also an Action).
        if hasattr(event, "source") and hasattr(event, "content"):
            s, r = self._score_message_event(event)  # type: ignore[arg-type]
            score += s
            reasons.extend(r)
        elif hasattr(event, "observation") or hasattr(event, "exit_code") or hasattr(event, "error"):
            s, r = self._score_observation_event(event)  # type: ignore[arg-type]
            score += s
            reasons.extend(r)
        elif hasattr(event, "action") or hasattr(event, "command"):
            s, r = self._score_action_event(event)  # type: ignore[arg-type]
            score += s
            reasons.extend(r)

        score = min(1.0, max(0.0, score))
        if not reasons:
            reasons.append("normal_importance")
        return score, reasons

    # ------------------------------------------------------------------
    # Selection/coherence helpers (unit-test visible)
    # ------------------------------------------------------------------

    def _select_events_to_keep(self, scored: list[EventImportance]) -> set[int]:
        if not scored:
            return set()

        events = [ei.event for ei in scored]
        keep: set[int] = set()

        # Always keep initial context
        for evt in events[: self.keep_first]:
            keep.add(int(getattr(evt, "id")))

        # Always keep a small recent window for coherence
        recent_window = min(5, len(events))
        for evt in events[-recent_window:]:
            keep.add(int(getattr(evt, "id")))

        # Keep events over importance threshold
        for ei in scored:
            if ei.importance_score >= self.importance_threshold:
                keep.add(int(getattr(ei.event, "id")))

        # Trim to max_size while protecting keep_first + recent window
        keep = self._trim_keep_set(scored, keep)
        return keep

    def _trim_keep_set(self, scored: list[EventImportance], keep: set[int]) -> set[int]:
        if len(keep) <= self.max_size:
            return keep

        events = [ei.event for ei in scored]
        protected = self._build_protected_ids(events)

        if len(protected) > self.max_size:
            return self._fallback_first_and_last(events)

        importance_by_id = {int(getattr(ei.event, "id")): ei.importance_score for ei in scored}
        droppable = sorted(
            (eid for eid in keep if eid not in protected),
            key=lambda eid: importance_by_id.get(eid, 0.0),
        )
        to_drop = len(keep) - self.max_size
        for eid in droppable[:to_drop]:
            keep.discard(eid)
        return keep

    def _build_protected_ids(self, events: list[Event]) -> set[int]:
        protected: set[int] = set()
        for evt in events[: self.keep_first]:
            protected.add(int(getattr(evt, "id")))
        for evt in events[-min(5, len(events)) :]:
            protected.add(int(getattr(evt, "id")))
        return protected

    def _fallback_first_and_last(self, events: list[Event]) -> set[int]:
        keep_ids = [int(getattr(e, "id")) for e in events[: self.keep_first]]
        remaining = max(0, self.max_size - len(keep_ids))
        tail = [int(getattr(e, "id")) for e in events[-remaining:]] if remaining else []
        return set(keep_ids + tail)

    def _ensure_coherence(self, events: list[Event], keep_ids: set[int]) -> set[int]:
        """Ensure action→observation pairs stay together when possible."""
        coherent = set(keep_ids)
        for idx, evt in enumerate(events[:-1]):
            evt_id = int(getattr(evt, "id"))
            if evt_id not in coherent:
                continue
            # Heuristic: actions have an 'action' attr; observations have an 'observation' attr.
            is_action = hasattr(evt, "action") and not hasattr(evt, "observation")
            if not is_action:
                continue
            nxt = events[idx + 1]
            if hasattr(nxt, "observation"):
                coherent.add(int(getattr(nxt, "id")))
        return coherent

    # ------------------------------------------------------------------
    # RollingCondenser hook
    # ------------------------------------------------------------------

    def get_condensation(self, view: View) -> Condensation:
        events = list(getattr(view, "events", []))
        if not events or len(events) <= self.max_size:
            return Condensation(action=CondensationAction(forgotten_event_ids=[]))

        scored: list[EventImportance] = []
        for evt in events:
            s, r = self._calculate_importance(evt)
            scored.append(EventImportance(event=evt, importance_score=s, reasons=r))

        keep_ids = self._select_events_to_keep(scored)
        keep_ids = self._ensure_coherence(events, keep_ids)
        keep_ids = self._trim_keep_set(scored, keep_ids)

        forgotten = [int(getattr(e, "id")) for e in events if int(getattr(e, "id")) not in keep_ids]
        return Condensation(action=CondensationAction(forgotten_event_ids=forgotten))
