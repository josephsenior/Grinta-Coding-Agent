"""Logic for detecting when an agent is stuck or looping ineffectively."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from backend.core.constants import (
    DEFAULT_STUCK_AB_PATTERN_WINDOW,
    DEFAULT_STUCK_CONDENSATION_LOOP_MIN,
    DEFAULT_STUCK_CONTEXT_HIGH_GROWTH,
    DEFAULT_STUCK_CONTEXT_HIGH_THRESHOLD,
    DEFAULT_STUCK_COST_ACCEL_TOKENS_PER_5_STEPS,
    DEFAULT_STUCK_RECENT_WINDOW,
    DEFAULT_STUCK_SEMANTIC_DIVERSITY,
    DEFAULT_STUCK_SEMANTIC_FAILURE_RATE,
    DEFAULT_STUCK_SEMANTIC_MIN_EVENTS,
    DEFAULT_STUCK_SEMANTIC_WINDOW,
    DEFAULT_STUCK_THINK_LOOP_DEPTH,
    DEFAULT_STUCK_TOKEN_REPETITION_MIN_CHARS,
)
from backend.core.logger import app_logger as logger
from backend.ledger.action.action import Action
from backend.ledger.action.agent import AgentThinkAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.empty import NullAction
from backend.ledger.action.files import FileEditAction, FileReadAction, FileWriteAction
from backend.ledger.action.message import MessageAction
from backend.ledger.event import Event, EventSource
from backend.ledger.observation import CmdOutputObservation
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.ledger.observation.empty import NullObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileEditObservation
from backend.ledger.observation.observation import Observation
from backend.orchestration.stuck_patterns import (
    eq_no_pid,
    has_enough_events_for_analysis,
    has_repeating_action_pattern,
    has_repeating_observation_pattern,
    is_stuck_monologue,
    is_stuck_repeating_action_error,
    is_stuck_repeating_action_observation,
)
from backend.validation.command_classification import classify_shell_intent

if TYPE_CHECKING:
    from backend.orchestration.state.state import State


class StuckDetector:
    """Detects when agent is stuck in unproductive loops or patterns.

    Analyzes agent's action history to identify syntax errors, semantic loops,
    and repeated failures that indicate the agent needs intervention.

    Attributes:
        SYNTAX_ERROR_MESSAGES: Common syntax error patterns to detect

    """

    SYNTAX_ERROR_MESSAGES = [
        'SyntaxError: unterminated string literal (detected at line',
        'SyntaxError: invalid syntax. Perhaps you forgot a comma?',
        'SyntaxError: incomplete input',
    ]

    def __init__(self, state: State) -> None:
        """Initialize stuck detector with agent state.

        Args:
            state: Current agent state to monitor

        """
        self.state = state

    def _get_history_to_check(self, headless_mode: bool) -> list[Event]:
        """Get the appropriate history to check based on headless mode."""
        if headless_mode:
            return self.state.history
        last_user_msg_idx = next(
            (
                len(self.state.history) - i - 1
                for i, event in enumerate(reversed(self.state.history))
                if isinstance(event, MessageAction) and event.source == EventSource.USER
            ),
            -1,
        )
        return self.state.history[last_user_msg_idx + 1 :]

    def _filter_relevant_history(self, history: Sequence[Event]) -> list[Event]:
        """Filter history to remove irrelevant events.

        Excludes user messages, null events, and error observations injected
        by the stuck detector itself (STUCK_LOOP_RECOVERY) or circuit breaker
        warnings to prevent a feedback loop where guard-injected errors
        trigger further stuck detections.
        """
        return [
            event
            for event in history
            if not (
                (isinstance(event, MessageAction) and event.source == EventSource.USER)
                or isinstance(event, NullAction | NullObservation)
                or (
                    isinstance(event, ErrorObservation)
                    and getattr(event, 'error_id', None)
                    in (
                        'STUCK_LOOP_RECOVERY',
                        'CIRCUIT_BREAKER_TRIPPED',
                        'CIRCUIT_BREAKER_WARNING',
                        'INCOMPLETE_TASK',
                    )
                )
            )
        ]

    def _collect_recent_events(
        self, filtered_history: list[Event]
    ) -> tuple[list[Event], list[Event]]:
        """Collect the last N actions and N observations from filtered history."""
        last_actions: list[Event] = []
        last_observations: list[Event] = []
        window = DEFAULT_STUCK_RECENT_WINDOW

        for event in reversed(filtered_history):
            if isinstance(event, Action) and len(last_actions) < window:
                last_actions.append(event)
            elif isinstance(event, Observation) and len(last_observations) < window:
                last_observations.append(event)
            if len(last_actions) == window and len(last_observations) == window:
                break

        return last_actions, last_observations

    def _check_basic_stuck_patterns(
        self,
        last_actions: list[Event],
        last_observations: list[Event],
        filtered_history: list[Event],
    ) -> bool:
        """Check for basic stuck patterns."""
        if is_stuck_repeating_action_observation(last_actions, last_observations):
            return True
        if is_stuck_repeating_action_error(last_actions, last_observations):
            return True
        return bool(is_stuck_monologue(filtered_history))

    def _check_advanced_stuck_patterns(self, filtered_history: list[Event]) -> bool:
        """Check for advanced stuck patterns."""
        if len(filtered_history) >= DEFAULT_STUCK_AB_PATTERN_WINDOW and self._is_stuck_action_observation_pattern(
            filtered_history
        ):
            return True
        return bool(
            len(filtered_history) >= DEFAULT_STUCK_CONDENSATION_LOOP_MIN
            and self._is_stuck_context_window_error(filtered_history)
        )

    def is_stuck(self, headless_mode: bool = True) -> bool:
        """Check if the agent is stuck in a deterministic repeat loop.

        Only the two hard signals are active here:

        1. **Exact action-observation repeat** (same action → same observation
           ≥ 3 times, or same action → error ≥ 3 times).  These are provably
           unproductive — there is no new information from retrying.
        2. **Monologue** — the agent emits the same message text 3+ times with
           no tool calls between them.

        All soft/heuristic signals (semantic loop, A-B-A-B, intent diversity,
        token repetition, cost acceleration, think-only, read-only loop) are
        intentionally excluded.  They have high false-positive rates on normal
        iterative work (TDD loops, exploration, refactoring sweeps) and their
        presence causes the stuck counter to accumulate even when the agent is
        making genuine progress.  Those helpers are still available for the
        ``compute_repetition_score`` telemetry path which does not affect
        control flow.

        Args:
            headless_mode: If True, consider all history.  If False, consider
                only history after the last user message (interactive mode).

        Returns:
            True only when a provably-stuck exact-repeat pattern is detected.
        """
        history_to_check = self._get_history_to_check(headless_mode)
        filtered_history = self._filter_relevant_history(history_to_check)

        if len(filtered_history) < 3:
            return False

        last_actions, last_observations = self._collect_recent_events(filtered_history)
        return self._check_basic_stuck_patterns(
            last_actions, last_observations, filtered_history
        )

    def _is_stuck_action_observation_pattern(
        self, filtered_history: list[Event]
    ) -> bool:
        """Check if there's a stuck action-observation pattern."""
        # Collect last 6 actions and observations
        last_six_actions, last_six_observations = self._collect_last_six_events(
            filtered_history
        )

        # Check if we have enough events to analyze
        if not has_enough_events_for_analysis(last_six_actions, last_six_observations):
            return False

        # Check for repeating patterns
        if has_repeating_action_pattern(
            last_six_actions
        ) and has_repeating_observation_pattern(
            last_six_observations,
        ):
            logger.warning('Action, Observation pattern detected')
            return True

        return False

    def _collect_last_six_events(
        self, filtered_history: list[Event]
    ) -> tuple[list[Event], list[Event]]:
        """Collect the last 6 actions and observations from filtered history."""
        last_six_actions: list[Event] = []
        last_six_observations: list[Event] = []

        for event in reversed(filtered_history):
            if isinstance(event, Action) and len(last_six_actions) < 6:
                last_six_actions.append(event)
            elif isinstance(event, Observation) and len(last_six_observations) < 6:
                last_six_observations.append(event)

            if len(last_six_actions) == 6 and len(last_six_observations) == 6:
                break

        return last_six_actions, last_six_observations

    def _has_enough_events_for_analysis(
        self,
        last_six_actions: list[Event],
        last_six_observations: list[Event],
    ) -> bool:
        """Check if we have enough events to analyze for patterns."""
        return len(last_six_actions) == 6 and len(last_six_observations) == 6

    def _has_repeating_action_pattern(self, last_six_actions: list[Event]) -> bool:
        """Check if there's a repeating action pattern."""
        return (
            eq_no_pid(last_six_actions[0], last_six_actions[2])
            and eq_no_pid(last_six_actions[0], last_six_actions[4])
            and eq_no_pid(last_six_actions[1], last_six_actions[3])
            and eq_no_pid(last_six_actions[1], last_six_actions[5])
        )

    def _has_repeating_observation_pattern(
        self, last_six_observations: list[Event]
    ) -> bool:
        """Check if there's a repeating observation pattern."""
        return (
            eq_no_pid(last_six_observations[0], last_six_observations[2])
            and eq_no_pid(last_six_observations[0], last_six_observations[4])
            and eq_no_pid(last_six_observations[1], last_six_observations[3])
            and eq_no_pid(last_six_observations[1], last_six_observations[5])
        )

    def _get_condensation_events(
        self, filtered_history: list[Event]
    ) -> list[tuple[int, Event]]:
        """Get all condensation events with their indices."""
        return [
            (i, event)
            for i, event in enumerate(filtered_history)
            if isinstance(event, AgentCondensationObservation)
        ]

    def _check_consecutive_condensation_events(
        self,
        last_condensation_events: list[tuple[int, Event]],
        filtered_history: list[Event],
    ) -> bool:
        """Check if there are consecutive condensation events without other events between them."""
        for i in range(len(last_condensation_events) - 1):
            start_idx = last_condensation_events[i][0]
            end_idx = last_condensation_events[i + 1][0]
            has_other_events = any(
                not isinstance(event, AgentCondensationObservation)
                for event in filtered_history[start_idx + 1 : end_idx]
            )
            if not has_other_events:
                logger.warning(
                    'Context window error loop detected - repeated condensation events'
                )
                return True
        return False

    def _is_stuck_context_window_error(self, filtered_history: list[Event]) -> bool:
        """Detects if we're stuck in a loop of context window errors.

        This happens when we repeatedly get context window errors and try to trim,
        but the trimming doesn't work, causing us to get more context window errors.
        The pattern is repeated AgentCondensationObservation events without any other
        events between them.

        Args:
            filtered_history: List of filtered events to check

        Returns:
            bool: True if we detect a context window error loop

        """
        condensation_events = self._get_condensation_events(filtered_history)
        if len(condensation_events) < DEFAULT_STUCK_CONDENSATION_LOOP_MIN:
            return False

        last_condensation_events = condensation_events[-DEFAULT_STUCK_CONDENSATION_LOOP_MIN:]
        return self._check_consecutive_condensation_events(
            last_condensation_events, filtered_history
        )

    def _is_stuck_semantic_loop(self, filtered_history: list[Event]) -> bool:
        """Detect semantic loops: different actions achieving same no-progress result.

        This catches cases where the agent:
        - Tries different commands but makes no progress
        - Repeats similar intents with different syntax
        - Gets same error in different ways

        Args:
            filtered_history: Filtered event history

        Returns:
            True if semantic loop detected

        """
        recent_window = filtered_history[-DEFAULT_STUCK_SEMANTIC_WINDOW:]
        action_intents, observation_outcomes = self._extract_intents_and_outcomes(
            recent_window
        )

        if (
            len(action_intents) < DEFAULT_STUCK_SEMANTIC_MIN_EVENTS
            or len(observation_outcomes) < DEFAULT_STUCK_SEMANTIC_MIN_EVENTS
        ):
            return False

        intent_diversity = self._calculate_intent_diversity(action_intents)
        failure_rate = self._calculate_failure_rate(observation_outcomes)

        # Detect semantic loop: very low diversity + very high failure rate
        # Raised thresholds to reduce false positives on legitimate diagnostic retries
        if (
            intent_diversity < DEFAULT_STUCK_SEMANTIC_DIVERSITY
            and failure_rate > DEFAULT_STUCK_SEMANTIC_FAILURE_RATE
        ):
            logger.warning(
                'Semantic loop detected: intent_diversity=%.2f, '
                'failure_rate=%.2f, unique_intents=%s/%s',
                intent_diversity,
                failure_rate,
                len(set(action_intents)),
                len(action_intents),
            )
            return True

        return False

    def _extract_intents_and_outcomes(
        self, events: list[Event]
    ) -> tuple[list[str], list[str]]:
        """Extract action intents and observation outcomes from events.

        Args:
            events: List of events to analyze

        Returns:
            Tuple of (action_intents, observation_outcomes)

        """
        action_intents = []
        observation_outcomes = []

        for event in events:
            if isinstance(event, Action) and not isinstance(
                event, NullAction | MessageAction
            ):
                intent = self._extract_action_intent(event)
                if intent:
                    action_intents.append(intent)
            elif isinstance(event, Observation) and not isinstance(
                event, NullObservation
            ):
                outcome = self._extract_observation_outcome(event)
                if outcome:
                    observation_outcomes.append(outcome)

        return action_intents, observation_outcomes

    def _categorize_cmd_action(self, command: str) -> str:
        """Classify a shell command for loop / diversity scoring (token-oriented)."""
        return classify_shell_intent(command)

    def _calculate_intent_diversity(self, action_intents: list[str]) -> float:
        """Calculate diversity of action intents.

        Args:
            action_intents: List of action intent strings

        Returns:
            Diversity ratio (unique/total)

        """
        if not action_intents:
            return 1.0

        unique_intents = len(set(action_intents))
        return unique_intents / len(action_intents)

    def _calculate_failure_rate(self, observation_outcomes: list[str]) -> float:
        """Calculate failure rate from observation outcomes.

        Args:
            observation_outcomes: List of outcome strings

        Returns:
            Failure rate ratio

        """
        if not observation_outcomes:
            return 0.0

        failures = sum(
            1 for outcome in observation_outcomes if outcome in ('error', 'no_change')
        )
        return failures / len(observation_outcomes)

    def _extract_action_intent(self, action: Action) -> str | None:
        """Extract the intent/goal of an action.

        Args:
            action: Action to analyze

        Returns:
            Intent category string or None

        """
        if isinstance(action, CmdRunAction):
            return self._categorize_cmd_action(action.command)
        if hasattr(action, 'path'):
            return f'file_op_{getattr(action, "path")}'
        return 'other_action'

    def _extract_observation_outcome(self, observation: Observation) -> str | None:
        """Extract the outcome/result of an observation.

        Args:
            observation: Observation to analyze

        Returns:
            Outcome category string or None

        """
        if isinstance(observation, ErrorObservation):
            return 'error'
        if isinstance(observation, CmdOutputObservation):
            return self._categorize_cmd_output(observation)
        content = getattr(observation, 'content', '') or ''
        if content.startswith('SKIPPED:'):
            return 'no_change'
        # Detect silent-success re-creation: old_content == new_content means
        # the file already existed and nothing was actually written.
        if isinstance(observation, FileEditObservation):
            old = getattr(observation, 'old_content', None)
            new = getattr(observation, 'new_content', None)
            if old is not None and old == new:
                return 'no_change'
        return 'unknown'

    def _categorize_cmd_output(self, observation: CmdOutputObservation) -> str:
        """Categorize command output from exit code and structured tool metadata only."""
        code = observation.exit_code
        if code is not None and code != 0:
            return 'error'
        tr_raw = getattr(observation, 'tool_result', None)
        tr = tr_raw if isinstance(tr_raw, dict) else None
        if tr is not None and tr.get('ok') is False:
            return 'error'
        if code == 0:
            if len((observation.content or '').strip()) == 0:
                return 'no_output'
            return 'success'
        if len((observation.content or '').strip()) == 0:
            return 'no_output'
        return 'unknown'

    def _is_stuck_token_repetition(self, filtered_history: list[Event]) -> bool:
        """Detect exact token-level repetition in agent messages.

        This is stricter than semantic loops - it catches when the LLM is
        outputting the exact same text stream repeatedly.
        """
        agent_msgs = [
            e
            for e in filtered_history
            if isinstance(e, MessageAction) and e.source == EventSource.AGENT
        ]

        if len(agent_msgs) < 3:
            return False

        # Check last 3 messages
        last_three = agent_msgs[-3:]

        # If all three have identical content
        if all(msg.content == last_three[0].content for msg in last_three[1:]):
            # Require non-trivial length to ignore short planning phrases
            if len(last_three[0].content) > DEFAULT_STUCK_TOKEN_REPETITION_MIN_CHARS:
                logger.warning(
                    'Token-level repetition detected (identical agent messages)'
                )
                return True

        return False

    def _is_stuck_cost_acceleration(self, filtered_history: list[Event]) -> bool:
        """Detect if token usage/cost is accelerating dangerously."""
        # Get events with metrics
        events_with_metrics = [
            e
            for e in filtered_history
            if e.llm_metrics is not None and e.llm_metrics.token_usages
        ]

        if len(events_with_metrics) < 10:
            return False

        # Extract prompt tokens for the last 10 steps
        prompt_tokens = self._get_prompt_token_history(events_with_metrics)
        if not prompt_tokens:
            return False

        # Check for rapid context growth (linear acceleration)
        # If context grows by > 2000 tokens over 5 steps?
        recent_growth = (
            prompt_tokens[-1] - prompt_tokens[-5] if len(prompt_tokens) >= 5 else 0
        )

        # If we added more than the configured threshold in 5 steps, that's
        # suspicious of a runaway loop (default 50k = avg 10k/step sustained).
        if recent_growth > DEFAULT_STUCK_COST_ACCEL_TOKENS_PER_5_STEPS:
            logger.warning(
                'Cost acceleration detected: %s tokens added in last 5 steps',
                recent_growth,
            )
            return True

        # Check specific cost spikes?
        # Maybe just raw context window check
        if prompt_tokens[-1] > DEFAULT_STUCK_CONTEXT_HIGH_THRESHOLD:
            # Check if we are still growing
            if recent_growth > DEFAULT_STUCK_CONTEXT_HIGH_GROWTH:
                logger.warning('High context window with continued growth detected')
                return True

        return False

    def _is_stuck_think_only_loop(self, filtered_history: list[Event]) -> bool:
        """Detect when agent calls think repeatedly without any real actions.

        Flash/lite models sometimes fall into a loop where they keep calling
        the 'think' tool without ever executing file edits, bash commands, or
        finishing the task.  Six or more consecutive AgentThinkActions with no
        non-think action between them is a clear signal of this pattern.
        """
        # Collect only Action events (ignore Observations, NullActions, etc.)
        recent_actions = [
            e
            for e in filtered_history[-30:]
            if isinstance(e, Action) and not isinstance(e, NullAction)
        ]

        if len(recent_actions) < DEFAULT_STUCK_THINK_LOOP_DEPTH:
            return False

        # Check if the last N actions are ALL AgentThinkAction
        if all(
            isinstance(a, AgentThinkAction)
            for a in recent_actions[-DEFAULT_STUCK_THINK_LOOP_DEPTH:]
        ):
            logger.warning(
                'Think-only loop detected: last 6+ actions are all AgentThinkAction '
                'with no real tool use.'
            )
            return True

        return False

    def _get_prompt_token_history(self, events_with_metrics: list[Event]) -> list[int]:
        """Extract prompt tokens for the last 10 steps."""
        prompt_tokens: list[int] = []
        for e in events_with_metrics[-10:]:
            llm_metrics = getattr(e, 'llm_metrics', None)
            token_usages = getattr(llm_metrics, 'token_usages', None)
            if not token_usages:
                continue
            try:
                candidate = token_usages[0].prompt_tokens
                if isinstance(candidate, bool):
                    continue
                prompt_tokens.append(int(candidate))
            except Exception:
                # Defensive: ignore unexpected shapes (e.g., MagicMock)
                continue
        return prompt_tokens

    def _score_action_repetition(self, last_actions: list) -> float:
        """Score for identical action repetition (0.0-1.0)."""
        if len(last_actions) < 2:
            return 0.0
        identical_count = sum(
            1 for a in last_actions[1:] if eq_no_pid(last_actions[0], a)
        )
        return min(1.0, identical_count / 3.0)

    def _score_observation_errors(self, last_observations: list) -> float:
        """Score for error rate in recent observations (0.0-1.0)."""
        if not last_observations:
            return 0.0
        error_count = sum(
            1
            for o in last_observations
            if isinstance(o, ErrorObservation)
            or (isinstance(o, CmdOutputObservation) and getattr(o, 'exit_code', 0) != 0)
        )
        return min(1.0, error_count / 3.0)

    def _score_intent_diversity(self, filtered_history: list) -> float:
        """Score for low semantic diversity (high = stuck)."""
        if len(filtered_history) < 10:
            return 0.0
        action_intents, _ = self._extract_intents_and_outcomes(filtered_history[-20:])
        if len(action_intents) < 4:
            return 0.0
        diversity = self._calculate_intent_diversity(action_intents)
        return max(0.0, 1.0 - diversity)

    def compute_repetition_score(self, headless_mode: bool = True) -> float:
        """Compute a 0.0-1.0 score indicating how close the agent is to being stuck.

        This allows the LLM to self-correct before the stuck detector formally triggers.
        Score meanings:
        - 0.0: No repetition detected
        - 0.3-0.5: Mild repetition patterns forming
        - 0.6-0.8: Strong repetition, approaching stuck threshold
        - 1.0: Would be flagged as stuck

        Args:
            headless_mode: Whether to check all history or only post-last-user-message

        Returns:
            Float between 0.0 and 1.0
        """
        history_to_check = self._get_history_to_check(headless_mode)
        filtered_history = self._filter_relevant_history(history_to_check)

        if len(filtered_history) < 3:
            return 0.0

        last_actions, last_observations = self._collect_recent_events(filtered_history)
        scores: list[float] = []
        scores.append(self._score_action_repetition(last_actions))
        scores.append(self._score_observation_errors(last_observations))
        scores.append(self._score_intent_diversity(filtered_history))
        scores = [s for s in scores if s > 0]

        return round(max(scores), 2) if scores else 0.0

    _READONLY_COMMANDS = frozenset(
        [
            'ls',
            'dir',
            'cat',
            'get-content',
            'type',
            'find',
            'pwd',
            'head',
            'tail',
            'more',
            'less',
            'wc',
            'file',
            'stat',
            'tree',
            'get-childitem',
            'get-item',
            'test-path',
            'resolve-path',
            'select-string',
            'get-location',
        ]
    )

    def _is_readonly_command(self, command: str) -> bool:
        """Check if a command is read-only (listing, reading, inspecting)."""
        cmd_lower = command.strip().lower()
        # Strip leading powershell call if present
        for prefix in ('powershell -c ', 'powershell.exe -c ', 'cmd /c '):
            if cmd_lower.startswith(prefix):
                cmd_lower = cmd_lower[len(prefix) :].strip().strip('"').strip("'")
                break
        first_token = cmd_lower.split()[0] if cmd_lower.split() else ''
        # Also handle piped/chained commands — check if ALL parts are read-only
        # For simplicity, check the first token and common patterns
        return (
            first_token in self._READONLY_COMMANDS
            or first_token.startswith('ls')
            or first_token.startswith('dir')
        )

    def _is_stuck_readonly_inspection_loop(self, filtered_history: list[Event]) -> bool:
        """Detect when agent only runs read-only commands without any writes.

        Disabled in normal operation — codebase exploration (many greps, reads, finds)
        is legitimate work, not a stuck loop. Only triggers on extreme cases: 20+
        read-only commands with near-zero diversity (<10% unique), which is a true
        degenerate poll loop (e.g., repeatedly calling the same `ls` with no args).
        The iteration limit and other heuristics handle genuine stuck cases.
        """
        window = filtered_history[-30:]
        readonly_commands: list[str] = []
        write_count = 0

        for e in window:
            if isinstance(e, CmdRunAction) and self._is_readonly_command(e.command):
                readonly_commands.append(e.command.strip())
            elif isinstance(e, FileReadAction):
                readonly_commands.append(f'__read__{getattr(e, "path", "")}')
            elif isinstance(e, (FileWriteAction, FileEditAction)):
                write_count += 1

        readonly_count = len(readonly_commands)
        if readonly_count < 20 or write_count > 0:
            return False

        unique_commands = len(set(readonly_commands))
        diversity = unique_commands / readonly_count if readonly_count else 1.0

        # Only fire on truly degenerate loops: 20+ reads, <10% unique commands
        if diversity < 0.10:
            logger.warning(
                'Read-only inspection loop detected: %d read-only actions '
                '(%d unique, %.0f%% diversity), %d writes in last %d events',
                readonly_count,
                unique_commands,
                diversity * 100,
                write_count,
                len(window),
            )
            return True

        return False
