"""Smart compactor with LLM-assisted importance scoring.

This compactor uses an LLM to score the importance of events and preserve
critical information during compaction, preventing loss of key insights.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.inference.llm import LLM

from backend.context.compactor.compactor import BaseLLMCompactor, Compaction
from backend.context.view import View
from backend.core.logger import app_logger as logger
from backend.ledger.action import Action, MessageAction
from backend.ledger.action.agent import CondensationAction, TaskTrackingAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation import ErrorObservation, Observation

_CRITICAL_ERROR_KEYWORDS = ('critical', 'crash', 'fatal', 'stuck')


class SmartCompactor(BaseLLMCompactor):
    """LLM-assisted compactor that preserves critical information.

    Uses an LLM to score event importance and preserve critical information
    during condensation, preventing loss of key insights.
    """

    def __init__(
        self,
        llm: LLM | None,
        max_size: int = 200,
        keep_first: int = 5,
        importance_threshold: float = 0.6,
        recency_bonus_window: int = 20,
    ) -> None:
        """Initialize the smart compactor.

        Args:
            llm: LLM instance for importance scoring
            max_size: Maximum events before condensation
            keep_first: Number of initial events to always keep
            importance_threshold: Minimum importance score to keep (0.0-1.0)
            recency_bonus_window: Number of recent events to give bonus
        """
        super().__init__(
            llm=llm,
            max_size=max_size,
            keep_first=keep_first,
        )
        self.importance_threshold = importance_threshold
        self.recency_bonus_window = recency_bonus_window

        logger.info(
            'SmartCompactor initialized: max_size=%s, threshold=%s, llm=%s',
            max_size,
            importance_threshold,
            llm.config.model if llm else 'none',
        )

    @staticmethod
    def _get_extra_config_args(config: Any) -> dict[str, Any]:
        """Get extra configuration arguments for the smart compactor."""
        return {
            'importance_threshold': getattr(config, 'importance_threshold', 0.6),
            'recency_bonus_window': getattr(config, 'recency_bonus_window', 20),
        }

    def get_compaction(self, view: View) -> Compaction:
        """Apply LLM-assisted condensation.

        Args:
            view: Current event view

        Returns:
            Condensation action specifying what to prune/summarize

        """
        events = list(view)

        if len(events) <= self.keep_first:
            # Not enough events to condense
            return Compaction(action=CondensationAction(pruned_event_ids=[]))

        # Identify essential events (always keep)
        essential_event_ids = self._identify_essential_events(events)

        # Score importance of remaining events
        importance_scores = self._score_event_importance(events, essential_event_ids)

        # Determine which events to keep
        events_to_keep = self._select_events_to_keep(
            events,
            essential_event_ids,
            importance_scores,
        )

        # Calculate pruned events.
        all_event_ids = {e.id for e in events}
        pruned_event_ids = sorted(all_event_ids - events_to_keep)

        logger.info(
            'SmartCompactor: Keeping %s events, pruning %s events',
            len(events_to_keep),
            len(pruned_event_ids),
        )

        return Compaction(action=CondensationAction(pruned_event_ids=pruned_event_ids))

    def _identify_essential_events(self, events: list[Event]) -> set[int]:
        """Identify essential events that must always be kept.

        Args:
            events: All events

        Returns:
            Set of essential event IDs

        """
        essential = set()
        for event in events[: self.keep_first]:
            essential.add(event.id)

        first_user = next(
            (
                e
                for e in events
                if isinstance(e, MessageAction) and e.source == EventSource.USER
            ),
            None,
        )
        if first_user:
            essential.add(first_user.id)

        for event in events:
            if isinstance(event, TaskTrackingAction):
                essential.add(event.id)

        self._anchor_active_plan_events(events, essential)
        self._add_critical_error_ids(events[-50:], essential)
        return essential

    def _add_critical_error_ids(self, events: list[Event], essential: set[int]) -> None:
        """Add IDs of ErrorObservation events with critical keywords to essential."""
        for event in events:
            if isinstance(event, ErrorObservation) and any(
                kw in event.content.lower() for kw in _CRITICAL_ERROR_KEYWORDS
            ):
                essential.add(event.id)

    def _anchor_active_plan_events(
        self, events: list[Event], essential: set[int]
    ) -> None:
        """Anchor the active plan's TaskTrackingAction as essential.

        Loads .app/active_plan.json and marks the most recent TaskTrackingAction
        event as essential. This creates a hard condensation anchor so the LLM
        always wakes up after condensation knowing exactly which task it was on.
        """
        in_progress_task_ids = self._load_in_progress_task_ids()
        if in_progress_task_ids:
            self._anchor_by_task_ids(events, essential, in_progress_task_ids)
        else:
            self._anchor_last_task_tracker(events, essential)

    def _load_in_progress_task_ids(self) -> set[str]:
        """Load in-progress task IDs from .app/active_plan.json, or empty set."""
        plan_path = (
            Path(os.environ.get('APP_WORKSPACE_DIR', '.')) / '.grinta' / 'active_plan.json'
        )
        tasks = self._parse_tasks_from_plan(plan_path)
        return self._extract_in_progress_ids(tasks)

    def _parse_tasks_from_plan(self, plan_path: Path) -> list[Any]:
        """Parse tasks from plan JSON. Returns empty list on failure."""
        if not plan_path.exists():
            return []
        try:
            plan = json.loads(plan_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(plan, dict):
            return plan.get('tasks', [])
        return plan if isinstance(plan, list) else []

    def _extract_in_progress_ids(self, tasks: list[Any]) -> set[str]:
        """Extract IDs of tasks with status 'in_progress'."""
        ids: set[str] = set()
        for task in tasks:
            if isinstance(task, dict) and task.get('status') == 'in_progress':
                tid = task.get('id') or task.get('title') or ''
                if tid:
                    ids.add(str(tid))
        return ids

    def _anchor_last_task_tracker(
        self, events: list[Event], essential: set[int]
    ) -> None:
        """Anchor the last TaskTrackingAction when no in-progress tasks exist."""
        for event in reversed(events):
            if isinstance(event, TaskTrackingAction):
                essential.add(event.id)
                logger.debug(
                    'SmartCompactor: anchored last TaskTrackingAction id=%s', event.id
                )
                break

    def _anchor_by_task_ids(
        self, events: list[Event], essential: set[int], in_progress_task_ids: set[str]
    ) -> None:
        """Anchor the most recent TaskTrackingAction that references an in-progress task."""
        for event in reversed(events):
            if isinstance(event, TaskTrackingAction):
                content = getattr(event, 'content', '') or ''
                if any(tid in content for tid in in_progress_task_ids):
                    essential.add(event.id)
                    logger.debug(
                        'SmartCompactor: anchored in-progress TaskTrackingAction id=%s',
                        event.id,
                    )
                    return
        self._anchor_last_task_tracker(events, essential)

    def _score_event_importance(
        self,
        events: list[Event],
        essential_ids: set[int],
    ) -> dict[int, float]:
        """Score importance of events using LLM.

        Args:
            events: All events
            essential_ids: IDs of essential events (don't score these)

        Returns:
            Dictionary mapping event ID to importance score (0.0-1.0)

        """
        scores: dict[int, float] = {}

        # Filter out essential events (they're already kept)
        events_to_score = [e for e in events if e.id not in essential_ids]

        if not events_to_score:
            return scores

        # Use heuristic scoring if LLM not available
        if not self.llm:
            return self._heuristic_scoring(events_to_score)

        # Group events into batches for efficient LLM scoring
        batch_size = 20
        for i in range(0, len(events_to_score), batch_size):
            batch = events_to_score[i : i + batch_size]
            batch_scores = self._score_event_batch_with_llm(batch)
            scores.update(batch_scores)

        return scores

    def _heuristic_scoring(self, events: list[Event]) -> dict[int, float]:
        """Score events using heuristics (fallback when no LLM).

        Args:
            events: Events to score

        Returns:
            Event ID to importance score mapping

        """
        scores: dict[int, float] = {}
        for event in events:
            scores[event.id] = self._heuristic_score_single(event)
        return scores

    def _heuristic_score_single(self, event: Event) -> float:
        """Return heuristic importance score for a single event."""
        if isinstance(event, MessageAction) and event.source == EventSource.USER:
            return 0.9
        if isinstance(event, TaskTrackingAction):
            return 1.0
        if isinstance(event, ErrorObservation):
            return 0.8
        if isinstance(event, Action) and getattr(event, 'runnable', False):
            return 0.7
        if isinstance(event, Observation) and len(event.content) > 500:
            return 0.6
        return 0.5

    def _score_event_batch_with_llm(self, events: list[Event]) -> dict[int, float]:
        """Score a batch of events using LLM.

        Args:
            events: Batch of events to score

        Returns:
            Event ID to importance score mapping

        """
        if self.llm is None:
            logger.debug('SmartCompactor: LLM not configured; skipping batch scoring.')
            return {}

        try:
            # Create scoring prompt
            prompt = self._create_scoring_prompt(events)

            # Get LLM response
            response = self.llm.completion(
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.3,
            )

            # Parse scores from response
            return self._parse_llm_scores(response, events)

        except Exception as e:
            logger.warning('LLM scoring failed, using heuristics: %s', e)
            return self._heuristic_scoring(events)

    def _create_scoring_prompt(self, events: list[Event]) -> str:
        """Create prompt for LLM importance scoring.

        Args:
            events: Events to score

        Returns:
            Scoring prompt

        """
        event_summaries = []

        for i, event in enumerate(events):
            event_type = type(event).__name__
            event_content = self._get_event_summary(event)
            event_summaries.append(f'{i}. [{event_type}] {event_content}')

        return f"""Score the importance of these conversation events for an autonomous agent task.

Events:
{chr(10).join(event_summaries)}

For each event, assign an importance score from 0.0 to 1.0:
- 1.0: Critical information (breakthroughs, solutions, critical errors)
- 0.7-0.9: Important (meaningful progress, key insights)
- 0.4-0.6: Moderate (useful context, routine operations)
- 0.0-0.3: Low importance (redundant info, trivial actions)

Respond ONLY with a JSON array of scores in order:
[0.8, 0.3, 0.9, ...]
"""

    def _get_event_summary(self, event: Event) -> str:
        """Get brief summary of event for scoring.

        Args:
            event: Event to summarize

        Returns:
            Summary string (truncated to 100 chars)

        """
        if hasattr(event, 'content'):
            return str(event.content)[:100]
        if hasattr(event, 'command'):
            return f'Command: {event.command[:50]}'
        if hasattr(event, 'code'):
            return f'Code: {event.code[:50]}'
        return str(event)[:100]

    def _parse_llm_scores(self, response, events: list[Event]) -> dict[int, float]:
        """Parse LLM response into event scores.

        Args:
            response: LLM response
            events: Events that were scored

        Returns:
            Event ID to score mapping

        """
        try:
            choices = getattr(response, 'choices', None)
            if not choices or len(choices) == 0:
                raise ValueError('LLM response has no choices')
            content = choices[0].message.content

            # Extract JSON array from response
            # Handle both raw array and wrapped in markdown
            if '```' in content:
                json_str = content.split('```')[1].strip()
                if json_str.startswith('json'):
                    json_str = json_str[4:].strip()
            else:
                json_str = content.strip()

            scores_list = json.loads(json_str)

            # Map to event IDs
            scores = {}
            for i, score in enumerate(scores_list):
                if i < len(events):
                    scores[events[i].id] = max(0.0, min(1.0, float(score)))

            return scores

        except Exception as e:
            logger.warning('Failed to parse LLM scores: %s', e)
            return self._heuristic_scoring(events)

    def _select_events_to_keep(
        self,
        events: list[Event],
        essential_ids: set[int],
        importance_scores: dict[int, float],
    ) -> set[int]:
        """Select which events to keep based on importance and recency.

        Args:
            events: All events
            essential_ids: Essential event IDs (always keep)
            importance_scores: Event importance scores

        Returns:
            Set of event IDs to keep

        """
        keep_ids = essential_ids.copy()

        # Apply recency bonus to recent events
        recent_events = events[-self.recency_bonus_window :]

        for event in events:
            if event.id in essential_ids:
                continue

            # Get base importance score
            base_score = importance_scores.get(event.id, 0.5)

            # Apply recency bonus
            if event in recent_events:
                recency_bonus = 0.3
                final_score = min(1.0, base_score + recency_bonus)
            else:
                final_score = base_score

            # Keep if above threshold
            if final_score >= self.importance_threshold:
                keep_ids.add(event.id)

        # Ensure action-observation pairs are preserved
        keep_ids = self._preserve_action_observation_pairs(events, keep_ids)

        # Ensure we keep at least recent events even if scores are low
        recent_ids = {e.id for e in events[-self.recency_bonus_window :]}
        keep_ids.update(recent_ids)

        return keep_ids

    def _preserve_action_observation_pairs(
        self,
        events: list[Event],
        keep_ids: set[int],
    ) -> set[int]:
        """Ensure action-observation pairs aren't broken.

        Args:
            events: All events
            keep_ids: Current set of IDs to keep

        Returns:
            Updated set with paired events

        """
        paired_ids = keep_ids.copy()

        for i, event in enumerate(events):
            if event.id not in keep_ids:
                continue

            if isinstance(event, Action) and hasattr(event, 'id'):
                self._pair_observation_for_action(events, i, event, paired_ids)
            elif isinstance(event, Observation) and event.cause is not None:
                self._pair_action_for_observation(events, i, event, paired_ids)

        return paired_ids

    def _pair_observation_for_action(
        self,
        events: list[Event],
        action_idx: int,
        action: Action,
        paired_ids: set[int],
    ) -> None:
        """Find and pair observation for an action.

        Args:
            events: All events
            action_idx: Index of action
            action: Action event
            paired_ids: Set to add paired IDs to

        """
        for j in range(action_idx + 1, min(action_idx + 5, len(events))):
            next_event = events[j]
            if isinstance(next_event, Observation):
                if next_event.cause == action.id:
                    paired_ids.add(next_event.id)
                break

    def _pair_action_for_observation(
        self,
        events: list[Event],
        obs_idx: int,
        observation: Observation,
        paired_ids: set[int],
    ) -> None:
        """Find and pair action for an observation.

        Args:
            events: All events
            obs_idx: Index of observation
            observation: Observation event
            paired_ids: Set to add paired IDs to

        """
        for j in range(max(0, obs_idx - 5), obs_idx):
            prev_event = events[j]
            if isinstance(prev_event, Action) and prev_event.id == observation.cause:
                paired_ids.add(prev_event.id)
                break


# Lazy registration to avoid circular imports
