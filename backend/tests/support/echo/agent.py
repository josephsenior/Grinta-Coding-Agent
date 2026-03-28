"""Deterministic dummy agent implementation for integration testing."""

from typing import TypedDict

from backend.orchestration.agent import Agent
from backend.orchestration.state.state import State
from backend.core.config import AgentConfig
from backend.core.schemas import AgentState
from backend.ledger.action import (
    Action,
    AgentRejectAction,
    CmdRunAction,
    FileReadAction,
    FileWriteAction,
    MessageAction,
    PlaybookFinishAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
    CmdOutputMetadata,
    CmdOutputObservation,
    FileReadObservation,
    FileWriteObservation,
    Observation,
)
from backend.ledger.serialization.event import event_to_dict
from backend.inference.llm_registry import LLMRegistry

# FIXME: There are a few problems this surfaced
# * FileWrites seem to add an unintended newline at the end of the file
# * Browser not working


class ActionObs(TypedDict):
    """Structure pairing a deterministic action with expected observations."""

    action: Action
    observations: list[Observation]


class Echo(Agent):
    """Deterministic agent used in integration tests for predictable behavior."""

    VERSION = "1.0"

    def __init__(self, config: AgentConfig, llm_registry: LLMRegistry) -> None:
        """Initialize the dummy agent with predefined test actions.

        Args:
            config: Agent configuration.
            llm_registry: LLM registry (unused, for interface compatibility).

        """
        super().__init__(config, llm_registry)
        self.steps: list[ActionObs] = [
            {"action": MessageAction("Time to get started!"), "observations": []},
            {
                "action": CmdRunAction(command='echo "foo"'),
                "observations": [
                    CmdOutputObservation(
                        "foo",
                        command='echo "foo"',
                        metadata=CmdOutputMetadata(exit_code=0),
                    ),
                ],
            },
            {
                "action": FileWriteAction(
                    content='echo "Hello, World!"', path="hello.sh"
                ),
                "observations": [FileWriteObservation(content="", path="hello.sh")],
            },
            {
                "action": FileReadAction(path="hello.sh"),
                "observations": [
                    FileReadObservation('echo "Hello, World!"\n', path="hello.sh")
                ],
            },
            {
                "action": CmdRunAction(command="bash hello.sh"),
                "observations": [
                    CmdOutputObservation(
                        "Hello, World!",
                        command="bash hello.sh",
                        metadata=CmdOutputMetadata(exit_code=0),
                    ),
                ],
            },
            {
                "action": AgentRejectAction(),
                "observations": [AgentStateChangedObservation("", AgentState.REJECTED)],
            },
            {
                "action": PlaybookFinishAction(
                    outputs={}, thought="Task completed", final_thought="Task completed"
                ),
                "observations": [AgentStateChangedObservation("", AgentState.FINISHED)],
            },
        ]

    def _remove_variable_fields(self, obs: dict) -> None:
        """Remove variable fields from observation."""
        obs.pop("id", None)
        obs.pop("timestamp", None)
        obs.pop("cause", None)
        obs.pop("source", None)

    def _normalize_metadata(self, obs: dict) -> None:
        """Normalize metadata by removing variable fields."""
        if "extras" not in obs or "metadata" not in obs["extras"]:
            return

        metadata = obs["extras"]["metadata"]
        if not isinstance(metadata, dict):
            return

        variable_fields = [
            "pid",
            "username",
            "hostname",
            "working_dir",
            "py_interpreter_path",
            "suffix",
        ]
        for field in variable_fields:
            metadata.pop(field, None)

    def _normalize_path(self, obs: dict) -> None:
        """Normalize path by keeping only the basename."""
        if "extras" not in obs or "path" not in obs["extras"]:
            return

        path = obs["extras"]["path"]
        if isinstance(path, str):
            import os

            obs["extras"]["path"] = os.path.basename(path)

    def _normalize_file_message(self, message: str, action: str) -> str:
        """Normalize file-related messages by keeping only basename."""
        import os

        pattern = f"I {action} the file "
        if pattern in message:
            parts = message.split(pattern)
            if len(parts) == 2:
                filename = os.path.basename(parts[1].rstrip("."))
                return f"I {action} the file {filename}."
        return message

    def _normalize_message(self, obs: dict) -> None:
        """Normalize message content."""
        if "message" not in obs:
            return

        message = obs["message"]
        if not isinstance(message, str):
            return

        # Normalize file write messages
        message = self._normalize_file_message(message, "wrote to")
        # Normalize file read messages
        message = self._normalize_file_message(message, "read")

        obs["message"] = message

    def _normalize_observation(self, obs: dict) -> None:
        """Normalize observation by removing variable fields and normalizing paths."""
        self._remove_variable_fields(obs)
        self._normalize_metadata(obs)
        self._normalize_path(obs)
        self._normalize_message(obs)

    def _validate_observations(self, state: State, prev_step: ActionObs) -> None:
        """Validate observations from the previous step."""
        if "observations" not in prev_step or not prev_step["observations"]:
            return

        expected_observations = prev_step["observations"]
        hist_events = state.view[-len(expected_observations) :]

        if len(hist_events) < len(expected_observations):
            pass

        for i in range(min(len(expected_observations), len(hist_events))):
            hist_obs = event_to_dict(hist_events[i])
            expected_obs = event_to_dict(expected_observations[i])

            # Normalize both observations
            for obs in [hist_obs, expected_obs]:
                self._normalize_observation(obs)

            if hist_obs != expected_obs:
                pass

    def step(self, state: State) -> Action:
        """Execute the next step in the dummy agent's predefined sequence."""
        if state.iteration_flag.current_value >= len(self.steps):
            return PlaybookFinishAction()

        current_step = self.steps[state.iteration_flag.current_value]

        # Validate observations from previous step
        if state.iteration_flag.current_value > 0:
            prev_step = self.steps[state.iteration_flag.current_value - 1]
            self._validate_observations(state, prev_step)

        return current_step["action"]
