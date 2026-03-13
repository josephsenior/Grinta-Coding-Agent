"""Logic for detecting when an agent is stuck or looping ineffectively."""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from backend.core.logger import forge_logger as logger
from backend.events.action.action import Action
from backend.events.action.agent import AgentThinkAction
from backend.events.action.commands import CmdRunAction
from backend.events.action.files import FileEditAction, FileReadAction, FileWriteAction
from backend.events.action.empty import NullAction
from backend.events.action.message import MessageAction
from backend.events.event import Event, EventSource
from backend.events.observation import CmdOutputObservation
from backend.events.observation.agent import AgentCondensationObservation
from backend.events.observation.empty import NullObservation
from backend.events.observation.error import ErrorObservation
from backend.events.observation.files import FileEditObservation
from backend.events.observation.observation import Observation

if TYPE_CHECKING:
    from backend.controller.state.state import State


class StuckDetector:
    """Detects when agent is stuck in unproductive loops or patterns.

    Analyzes agent's action history to identify syntax errors, semantic loops,
    and repeated failures that indicate the agent needs intervention.

    Attributes:
        SYNTAX_ERROR_MESSAGES: Common syntax error patterns to detect

    """

    SYNTAX_ERROR_MESSAGES = [
        "SyntaxError: unterminated string literal (detected at line",
        "SyntaxError: invalid syntax. Perhaps you forgot a comma?",
        "SyntaxError: incomplete input",
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
        by the stuck detector itself (STUCK_LOOP_RECOVERY) to prevent a
        feedback loop where stuck-recovery errors trigger further stuck
        detections.
        """
        return [
            event
            for event in history
            if not (
                (isinstance(event, MessageAction) and event.source == EventSource.USER)
                or isinstance(event, NullAction | NullObservation)
                or (
                    isinstance(event, ErrorObservation)
                    and getattr(event, "error_id", None) in (
                        "STUCK_LOOP_RECOVERY",
                        "CIRCUIT_BREAKER_TRIPPED",
                        "INCOMPLETE_TASK",
                    )
                )
            )
        ]

    def _collect_recent_events(
        self, filtered_history: list[Event]
    ) -> tuple[list[Event], list[Event]]:
        """Collect the last 4 actions and 4 observations from filtered history."""
        last_actions: list[Event] = []
        last_observations: list[Event] = []

        for event in reversed(filtered_history):
            if isinstance(event, Action) and len(last_actions) < 4:
                last_actions.append(event)
            elif isinstance(event, Observation) and len(last_observations) < 4:
                last_observations.append(event)
            if len(last_actions) == 4 and len(last_observations) == 4:
                break

        return last_actions, last_observations

    def _check_basic_stuck_patterns(
        self,
        last_actions: list[Event],
        last_observations: list[Event],
        filtered_history: list[Event],
    ) -> bool:
        """Check for basic stuck patterns."""
        if self._is_stuck_repeating_action_observation(last_actions, last_observations):
            return True
        if self._is_stuck_repeating_action_error(last_actions, last_observations):
            return True
        return bool(self._is_stuck_monologue(filtered_history))

    def _check_advanced_stuck_patterns(self, filtered_history: list[Event]) -> bool:
        """Check for advanced stuck patterns."""
        if len(filtered_history) >= 6 and self._is_stuck_action_observation_pattern(
            filtered_history
        ):
            return True
        return bool(
            len(filtered_history) >= 10
            and self._is_stuck_context_window_error(filtered_history)
        )

    def is_stuck(self, headless_mode: bool = True) -> bool:
        """Check if the agent is stuck in a loop.

        Args:
            headless_mode: Matches AgentController's headless_mode.
                          If True: Consider all history (automated/testing)
                          If False: Consider only history after last user message (interactive)

        Returns:
            bool: True if the agent is stuck in a loop, False otherwise.

        """
        history_to_check = self._get_history_to_check(headless_mode)
        filtered_history = self._filter_relevant_history(history_to_check)

        if len(filtered_history) < 3:
            return False

        last_actions, last_observations = self._collect_recent_events(filtered_history)

        # Check basic stuck patterns
        if self._check_basic_stuck_patterns(
            last_actions, last_observations, filtered_history
        ):
            return True

        # Check advanced stuck patterns
        if self._check_advanced_stuck_patterns(filtered_history):
            return True

        # NEW: Check semantic stuck patterns (different actions, same no-progress result)
        if len(filtered_history) >= 10:
            if self._is_stuck_semantic_loop(filtered_history):
                return True

        # NEW: Check for token-level repetition
        if self._is_stuck_token_repetition(filtered_history):
            return True

        # NEW: Check for cost acceleration
        if self._is_stuck_cost_acceleration(filtered_history):
            return True

        # Check for think-only loops (model calls think repeatedly, no real actions)
        if self._is_stuck_think_only_loop(filtered_history):
            return True

        # Check for read-only verification loops (ls, cat, Get-Content with no writes)
        if self._is_stuck_readonly_inspection_loop(filtered_history):
            return True

        return False

    def _check_actions_equal(self, last_actions: list[Event]) -> bool:
        """Check if all actions in the list are equal (ignoring PID)."""
        return all(self._eq_no_pid(last_actions[0], action) for action in last_actions)

    def _check_observations_equal(self, last_observations: list[Event]) -> bool:
        """Check if all observations in the list are equal (ignoring PID)."""
        return all(
            self._eq_no_pid(last_observations[0], observation)
            for observation in last_observations
        )

    def _is_stuck_repeating_action_observation(
        self, last_actions: list[Event], last_observations: list[Event]
    ) -> bool:
        if len(last_actions) == 4 and len(last_observations) == 4:
            actions_equal = self._check_actions_equal(last_actions)
            observations_equal = self._check_observations_equal(last_observations)
            if actions_equal and observations_equal:
                logger.warning("Action, Observation loop detected")
                return True
        return False

    def _is_stuck_repeating_action_error(
        self, last_actions: list[Event], last_observations: list[Event]
    ) -> bool:
        """Check if there's a stuck repeating action-error pattern."""
        # Check if we have enough events to analyze
        if not self._has_enough_events_for_error_analysis(
            last_actions, last_observations
        ):
            return False

        # Check if actions are repeating
        if not self._are_actions_repeating(last_actions):
            return False

        # Check for error observation patterns
        return self._check_error_observation_patterns(last_observations)

    def _has_enough_events_for_error_analysis(
        self, last_actions: list[Event], last_observations: list[Event]
    ) -> bool:
        """Check if we have enough events to analyze for error patterns."""
        return len(last_actions) >= 3 and len(last_observations) >= 3

    def _are_actions_repeating(self, last_actions: list[Event]) -> bool:
        """Check if the last 3 actions are all the same."""
        return all(
            self._eq_no_pid(last_actions[0], action) for action in last_actions[:3]
        )

    def _check_error_observation_patterns(self, last_observations: list[Event]) -> bool:
        """Check for various error observation patterns."""
        # Check for simple error observations
        return self._check_simple_error_observations(last_observations)

    def _check_simple_error_observations(self, last_observations: list[Event]) -> bool:
        """Check for simple error observation patterns."""
        if all(isinstance(obs, ErrorObservation) for obs in last_observations[:3]):
            logger.warning("Action, ErrorObservation loop detected")
            return True
        return False

    def _is_stuck_monologue(self, filtered_history: list[Event]) -> bool:
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
                    logger.warning("Repeated MessageAction with source=AGENT detected")
                    return True
        return False

    def _is_stuck_action_observation_pattern(
        self, filtered_history: list[Event]
    ) -> bool:
        """Check if there's a stuck action-observation pattern."""
        # Collect last 6 actions and observations
        last_six_actions, last_six_observations = self._collect_last_six_events(
            filtered_history
        )

        # Check if we have enough events to analyze
        if not self._has_enough_events_for_analysis(
            last_six_actions, last_six_observations
        ):
            return False

        # Check for repeating patterns
        if self._has_repeating_action_pattern(
            last_six_actions
        ) and self._has_repeating_observation_pattern(
            last_six_observations,
        ):
            logger.warning("Action, Observation pattern detected")
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
            self._eq_no_pid(last_six_actions[0], last_six_actions[2])
            and self._eq_no_pid(last_six_actions[0], last_six_actions[4])
            and self._eq_no_pid(last_six_actions[1], last_six_actions[3])
            and self._eq_no_pid(last_six_actions[1], last_six_actions[5])
        )

    def _has_repeating_observation_pattern(
        self, last_six_observations: list[Event]
    ) -> bool:
        """Check if there's a repeating observation pattern."""
        return (
            self._eq_no_pid(last_six_observations[0], last_six_observations[2])
            and self._eq_no_pid(last_six_observations[0], last_six_observations[4])
            and self._eq_no_pid(last_six_observations[1], last_six_observations[3])
            and self._eq_no_pid(last_six_observations[1], last_six_observations[5])
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
                    "Context window error loop detected - repeated condensation events"
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
        if len(condensation_events) < 10:
            return False

        last_condensation_events = condensation_events[-10:]
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
        recent_window = filtered_history[-20:]
        action_intents, observation_outcomes = self._extract_intents_and_outcomes(
            recent_window
        )

        if len(action_intents) < 6 or len(observation_outcomes) < 6:
            return False

        intent_diversity = self._calculate_intent_diversity(action_intents)
        failure_rate = self._calculate_failure_rate(observation_outcomes)

        # Detect semantic loop: low diversity + high failure rate
        if intent_diversity < 0.4 and failure_rate > 0.6:
            logger.warning(
                "Semantic loop detected: intent_diversity=%.2f, "
                "failure_rate=%.2f, unique_intents=%s/%s",
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
            1
            for outcome in observation_outcomes
            if outcome in ["error", "no_change", "not_found"]
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
            return self._categorize_cmd_action(action.command.lower())
        return "other_action"

    def _categorize_cmd_action(self, command: str) -> str:
        """Categorize command action by type.

        Args:
            command: Lowercased command string

        Returns:
            Category string

        """
        # Command categories with their patterns
        categories = [
            (["pytest", "npm test", "cargo test", "go test"], "run_test"),
            (["cat", "ls", "pwd", "find", "get-content", "get-childitem", "dir", "type", "tree"], "inspect_filesystem"),
            (["git clone", "git pull", "git fetch"], "fetch_code"),
            (["pip install", "npm install", "cargo build"], "install_dependency"),
            (["mkdir", "touch", "echo >"], "create_file"),
            (["rm", "rmdir"], "delete_file"),
            (["python", "node", "cargo run"], "execute_code"),
        ]

        for patterns, category in categories:
            if any(cmd in command for cmd in patterns):
                return category

        return "other_command"

    def _extract_observation_outcome(self, observation: Observation) -> str | None:
        """Extract the outcome/result of an observation.

        Args:
            observation: Observation to analyze

        Returns:
            Outcome category string or None

        """
        if isinstance(observation, ErrorObservation):
            return "error"
        if isinstance(observation, CmdOutputObservation):
            return self._categorize_cmd_output(observation)
        # Detect file-create-already-exists (SKIPPED) as no_change
        content = getattr(observation, "content", "") or ""
        if content.startswith("SKIPPED:") or "already exists" in content:
            return "no_change"
        # Detect silent-success re-creation: old_content == new_content means
        # the file already existed and nothing was actually written.
        if isinstance(observation, FileEditObservation):
            old = getattr(observation, "old_content", None)
            new = getattr(observation, "new_content", None)
            if old is not None and old == new:
                return "no_change"
        return "unknown"

    def _categorize_cmd_output(self, observation: CmdOutputObservation) -> str:
        """Categorize command output observation.

        Args:
            observation: Command output observation

        Returns:
            Outcome category string

        """
        if observation.exit_code != 0:
            return "error"

        content_lower = observation.content.lower()

        if "no such file" in content_lower or "not found" in content_lower:
            return "not_found"
        if "permission denied" in content_lower:
            return "permission_error"
        if len(observation.content.strip()) == 0:
            return "no_output"
        return "success"

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
            # And the content is non-trivial (ignore empty/short acks)
            if len(last_three[0].content) > 10:
                logger.warning(
                    "Token-level repetition detected (identical agent messages)"
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

        # If we added more than 10k tokens in 5 steps, that's suspicious of a runaway loop
        # (Average 2k per step is high but possible, but sustained high growth is bad)
        if recent_growth > 10000:
            logger.warning(
                "Cost acceleration detected: %s tokens added in last 5 steps",
                recent_growth,
            )
            return True

        # Check specific cost spikes?
        # Maybe just raw context window check
        if prompt_tokens[-1] > 100000:  # 100k context warning
            # Check if we are still growing
            if recent_growth > 1000:
                logger.warning("High context window with continued growth detected")
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

        if len(recent_actions) < 6:
            return False

        # Check if the last 6 actions are ALL AgentThinkAction
        if all(isinstance(a, AgentThinkAction) for a in recent_actions[-6:]):
            logger.warning(
                "Think-only loop detected: last 6+ actions are all AgentThinkAction "
                "with no real tool use."
            )
            return True

        return False

    def _get_prompt_token_history(self, events_with_metrics: list[Event]) -> list[int]:
        """Extract prompt tokens for the last 10 steps."""
        prompt_tokens: list[int] = []
        for e in events_with_metrics[-10:]:
            llm_metrics = getattr(e, "llm_metrics", None)
            token_usages = getattr(llm_metrics, "token_usages", None)
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
            1 for a in last_actions[1:] if self._eq_no_pid(last_actions[0], a)
        )
        return min(1.0, identical_count / 3.0)

    def _score_observation_errors(self, last_observations: list) -> float:
        """Score for error rate in recent observations (0.0-1.0)."""
        if not last_observations:
            return 0.0
        error_count = sum(
            1 for o in last_observations
            if isinstance(o, ErrorObservation)
            or (isinstance(o, CmdOutputObservation) and getattr(o, "exit_code", 0) != 0)
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

    _READONLY_COMMANDS = frozenset([
        "ls", "dir", "cat", "get-content", "type", "find", "pwd",
        "head", "tail", "more", "less", "wc", "file", "stat", "tree",
        "get-childitem", "get-item", "test-path", "resolve-path",
        "select-string", "get-location",
    ])

    def _is_readonly_command(self, command: str) -> bool:
        """Check if a command is read-only (listing, reading, inspecting)."""
        cmd_lower = command.strip().lower()
        # Strip leading powershell call if present
        for prefix in ("powershell -c ", "powershell.exe -c ", "cmd /c "):
            if cmd_lower.startswith(prefix):
                cmd_lower = cmd_lower[len(prefix):].strip().strip('"').strip("'")
                break
        first_token = cmd_lower.split()[0] if cmd_lower.split() else ""
        # Also handle piped/chained commands — check if ALL parts are read-only
        # For simplicity, check the first token and common patterns
        return first_token in self._READONLY_COMMANDS or first_token.startswith("ls") or first_token.startswith("dir")

    def _is_stuck_readonly_inspection_loop(self, filtered_history: list[Event]) -> bool:
        """Detect when agent only runs read-only commands without any writes.

        This catches verification loops where the agent repeatedly does
        ls/dir, cat/Get-Content, or file reads without creating new content.
        Any write (even to an existing path) counts as progress to avoid
        false positives during multi-file creation tasks.

        To avoid false positives on legitimate research/exploration, we only
        trigger when the agent repeats the SAME readonly command multiple
        times (low diversity).  Diverse exploration (different directories)
        is considered progress.
        """
        # Use a window of last 20 events — only trigger if overwhelmingly read-only
        window = filtered_history[-20:]
        readonly_commands: list[str] = []
        write_count = 0

        for e in window:
            if isinstance(e, CmdRunAction) and self._is_readonly_command(e.command):
                readonly_commands.append(e.command.strip())
            elif isinstance(e, FileReadAction):
                readonly_commands.append(f"__read__{getattr(e, 'path', '')}")
            elif isinstance(e, (FileWriteAction, FileEditAction)):
                write_count += 1

        readonly_count = len(readonly_commands)
        if readonly_count < 5 or write_count > 0:
            return False

        # Check diversity: if commands are diverse (exploring different paths),
        # that's legitimate research, not a loop
        unique_commands = len(set(readonly_commands))
        diversity = unique_commands / readonly_count if readonly_count else 1.0

        # Low diversity (< 50% unique) = stuck loop
        # High diversity = legitimate exploration
        if diversity < 0.5:
            logger.warning(
                "Read-only inspection loop detected: %d read-only actions "
                "(%d unique, %.0f%% diversity), %d writes in last %d events",
                readonly_count,
                unique_commands,
                diversity * 100,
                write_count,
                len(window),
            )
            return True

        return False

    def _eq_no_pid(self, obj1: Event, obj2: Event) -> bool:
        if isinstance(obj1, CmdRunAction) and isinstance(obj2, CmdRunAction):
            return obj1.command == obj2.command
        if isinstance(obj1, CmdOutputObservation) and isinstance(
            obj2, CmdOutputObservation
        ):
            return obj1.command == obj2.command and obj1.exit_code == obj2.exit_code
        return obj1 == obj2
