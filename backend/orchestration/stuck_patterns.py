"""Pattern detection logic for stuck agent detection.

Extracted from StuckDetector to improve testability and reduce
the size of stuck.py. These functions operate on event lists
and use eq_no_pid for comparison.
"""

from __future__ import annotations

import re

from backend.core.logger import app_logger as logger
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.message import MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.observation import Observation

# Patterns that represent dynamic/ephemeral values in observation content.
# Stripping these before comparison lets us detect loops where the model
# hits the same underlying error but the message varies in line numbers,
# temp file paths, timestamps, memory addresses, or elapsed time.
_DYNAMIC_CONTENT_RE = re.compile(
    r'(?:'
    r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'  # ISO timestamps
    r'|(?<!\w)\d{10,}(?!\w)'          # Unix epoch integers (10+ digits)
    r'|0x[0-9a-fA-F]+'               # hex memory addresses
    r'|/tmp/[^\s,;"\')]*'            # /tmp/... paths
    r'|\\[Tt]emp\\[^\s,;"\')]*'      # Windows \Temp\... paths
    r'|(?:line|col(?:umn)?)\s+\d+'   # "line N" / "column N"
    r'|:\d+(?::\d+)?(?=\D|$)'        # :42 or :42:8 (file:line:col)
    r'|in \d+\.\d+s'                 # "in 0.12s" timing
    r')',
    re.IGNORECASE,
)


def _normalize_obs_content(content: str) -> str:
    """Strip dynamic values from observation content for comparison purposes.

    Replaces timestamps, memory addresses, temp paths, line/column numbers,
    and elapsed-time strings with a fixed placeholder so that two observations
    that differ only in ephemeral details compare as equal.
    """
    return _DYNAMIC_CONTENT_RE.sub('<_>', content).strip()


def eq_no_pid(obj1: Event, obj2: Event) -> bool:
    """Compare two events ignoring process IDs and ephemeral dynamic values."""
    if isinstance(obj1, CmdRunAction) and isinstance(obj2, CmdRunAction):
        return obj1.command == obj2.command
    if isinstance(obj1, CmdOutputObservation) and isinstance(
        obj2, CmdOutputObservation
    ):
        return obj1.command == obj2.command and obj1.exit_code == obj2.exit_code
    # For error observations, normalize dynamic content before comparing so
    # that the same underlying error surfacing with slightly different line
    # numbers or temp paths is correctly identified as a repeat.
    if isinstance(obj1, ErrorObservation) and isinstance(obj2, ErrorObservation):
        return _normalize_obs_content(
            getattr(obj1, 'content', '')
        ) == _normalize_obs_content(getattr(obj2, 'content', ''))
    return obj1 == obj2


def check_actions_equal(last_actions: list[Event]) -> bool:
    """Check if all actions in the list are equal (ignoring PID)."""
    if not last_actions:
        return False
    return all(eq_no_pid(last_actions[0], action) for action in last_actions)


def check_observations_equal(last_observations: list[Event]) -> bool:
    """Check if all observations in the list are equal (ignoring PID)."""
    if not last_observations:
        return False
    return all(
        eq_no_pid(last_observations[0], observation)
        for observation in last_observations
    )


def is_stuck_repeating_action_observation(
    last_actions: list[Event], last_observations: list[Event]
) -> bool:
    """Check for action-observation loop (same action, same observation repeated)."""
    if len(last_actions) == 4 and len(last_observations) == 4:
        if check_actions_equal(last_actions) and check_observations_equal(
            last_observations
        ):
            logger.warning('Action, Observation loop detected')
            return True
    return False


def has_enough_events_for_error_analysis(
    last_actions: list[Event], last_observations: list[Event]
) -> bool:
    """Check if we have enough events to analyze for error patterns."""
    return len(last_actions) >= 3 and len(last_observations) >= 3


def are_actions_repeating(last_actions: list[Event]) -> bool:
    """Check if the last 3 actions are all the same."""
    if len(last_actions) < 3:
        return False
    return all(eq_no_pid(last_actions[0], action) for action in last_actions[:3])


def check_simple_error_observations(last_observations: list[Event]) -> bool:
    """Check for simple error observation patterns (all ErrorObservation)."""
    if len(last_observations) < 3:
        return False
    if all(isinstance(obs, ErrorObservation) for obs in last_observations[:3]):
        logger.warning('Action, ErrorObservation loop detected')
        return True
    return False


def is_stuck_repeating_action_error(
    last_actions: list[Event], last_observations: list[Event]
) -> bool:
    """Check if there's a stuck repeating action-error pattern."""
    if not has_enough_events_for_error_analysis(last_actions, last_observations):
        return False
    if not are_actions_repeating(last_actions):
        return False
    return check_simple_error_observations(last_observations)


def has_enough_events_for_analysis(
    last_six_actions: list[Event], last_six_observations: list[Event]
) -> bool:
    """Check if we have enough events to analyze for patterns."""
    return len(last_six_actions) == 6 and len(last_six_observations) == 6


def has_repeating_action_pattern(last_six_actions: list[Event]) -> bool:
    """Check if there's a repeating action pattern (A-B-A-B-A-B)."""
    if len(last_six_actions) < 6:
        return False
    return (
        eq_no_pid(last_six_actions[0], last_six_actions[2])
        and eq_no_pid(last_six_actions[0], last_six_actions[4])
        and eq_no_pid(last_six_actions[1], last_six_actions[3])
        and eq_no_pid(last_six_actions[1], last_six_actions[5])
    )


def has_repeating_observation_pattern(
    last_six_observations: list[Event],
) -> bool:
    """Check if there's a repeating observation pattern."""
    if len(last_six_observations) < 6:
        return False
    return (
        eq_no_pid(last_six_observations[0], last_six_observations[2])
        and eq_no_pid(last_six_observations[0], last_six_observations[4])
        and eq_no_pid(last_six_observations[1], last_six_observations[3])
        and eq_no_pid(last_six_observations[1], last_six_observations[5])
    )


def is_stuck_monologue(filtered_history: list[Event]) -> bool:
    """Check for repeated MessageAction with source=AGENT without observations between."""
    agent_message_actions = [
        (i, event)
        for i, event in enumerate(filtered_history)
        if isinstance(event, MessageAction) and event.source == EventSource.AGENT
    ]
    if len(agent_message_actions) >= 3:
        last_agent_message_actions = agent_message_actions[-3:]
        if all(
            last_agent_message_actions[0][1] == action[1]
            for action in last_agent_message_actions
        ):
            start_index = last_agent_message_actions[0][0]
            end_index = last_agent_message_actions[-1][0]
            has_observation_between = any(
                isinstance(event, Observation)
                for event in filtered_history[start_index + 1 : end_index]
            )
            if not has_observation_between:
                logger.warning('Repeated MessageAction with source=AGENT detected')
                return True
    return False
