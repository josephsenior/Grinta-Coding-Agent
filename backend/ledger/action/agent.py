"""Agent-focused action types emitted in Grinta event streams."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from backend.core.enums import RecallType
from backend.core.schemas import ActionType, AgentState
from backend.ledger.action.action import Action


@dataclass
class ChangeAgentStateAction(Action):
    """Fake action, just to notify the client that a task state has changed."""

    agent_state: AgentState | str = ''
    thought: str = ''
    action: ClassVar[str] = ActionType.CHANGE_AGENT_STATE

    @property
    def message(self) -> str:
        """Get human-readable message for state change."""
        return f'Agent state changed to {self.agent_state}'


@dataclass
class AgentThinkAction(Action):
    """An action where the agent logs a thought.

    Attributes:
        thought (str): The agent's explanation of its actions.
        suppress_cli (bool): When True, the CLI transcript/reasoning UI skips this
            thought (still recorded for the agent / history).
        source_tool (str): When set, identifies the tool that produced this think action
            (e.g. 'checkpoint') so the CLI can render a proper
            activity row instead of generic reasoning text.
        kind (str): Internal classification tag used by the renderer to decide how
            to display the thought. Empty string means a normal reasoning thought.
            Known values:
              - ``'recoverable_error'`` -- the LLM's last tool call was invalid and
                the thought contains recovery guidance. Render as an error card.
              - ``'recoverable_error_escalated'`` -- the same recoverable error has
                fired repeatedly and was blocked. Render as a louder error card.
              - ``'truncated'`` -- the LLM's tool call arguments were stream-truncated.
                Render as an error card.
            The kind is metadata only and is NOT included in the LLM-facing text.
        action (str): The action type, namely ActionType.THINK.

    """

    thought: str = ''
    suppress_cli: bool = False
    source_tool: str = ''
    kind: str = ''
    action: ClassVar[str] = ActionType.THINK

    KIND_RECOVERABLE_ERROR: ClassVar[str] = 'recoverable_error'
    KIND_RECOVERABLE_ERROR_ESCALATED: ClassVar[str] = 'recoverable_error_escalated'
    KIND_TRUNCATED: ClassVar[str] = 'truncated'

    @property
    def message(self) -> str:
        """Get formatted thinking message."""
        return f'I am thinking...: {self.thought}'


@dataclass
class SystemHintAction(Action):
    """A system-generated hint fed back to the LLM as external feedback.

    Unlike :class:`AgentThinkAction` (which represents the LLM's own
    reasoning and renders as ``role='assistant'``), ``SystemHintAction``
    renders as ``role='user'`` so the LLM correctly perceives the content
    as environment/system feedback rather than its own prior thoughts.

    Attributes:
        thought (str): The hint message to feed back to the LLM.
        kind (str): Classification tag used by the renderer to decide how
            to display the hint. Known values:
              - ``'recoverable_error'`` -- the LLM's last tool call was
                invalid and the thought contains recovery guidance.
              - ``'recoverable_error_escalated'`` -- the same recoverable
                error has fired repeatedly and was blocked.
              - ``'truncated'`` -- the LLM's tool call arguments were
                stream-truncated.
            The kind is metadata only and is NOT included in the
            LLM-facing text.
        source_tool (str): When set, identifies the tool that produced
            this hint (e.g. ``'task_tracker'``) so the CLI can render a
            proper activity row.
        suppress_cli (bool): When True, the CLI transcript skips this
            hint (still recorded for the agent / history).
        action (str): The action type, namely ActionType.SYSTEM_HINT.
    """

    thought: str = ''
    kind: str = ''
    source_tool: str = ''
    suppress_cli: bool = False
    action: ClassVar[str] = ActionType.SYSTEM_HINT

    KIND_RECOVERABLE_ERROR: ClassVar[str] = 'recoverable_error'
    KIND_RECOVERABLE_ERROR_ESCALATED: ClassVar[str] = 'recoverable_error_escalated'
    KIND_TRUNCATED: ClassVar[str] = 'truncated'

    @property
    def message(self) -> str:
        """Get formatted system hint message."""
        return f'[SYSTEM] {self.thought}'


@dataclass
class AgentRejectAction(Action):
    """An action where the agent rejects the task."""

    outputs: dict[str, Any] = field(default_factory=dict)
    thought: str = ''
    action: ClassVar[str] = ActionType.REJECT

    @property
    def message(self) -> str:
        """Get rejection message with optional reason."""
        msg: str = 'Task is rejected by the agent.'
        if 'reason' in self.outputs:
            msg += ' Reason: ' + self.outputs['reason']
        return msg


@dataclass
class RecallAction(Action):
    """This action is used for retrieving content, e.g., from the global directory or user workspace."""

    recall_type: RecallType = RecallType.WORKSPACE_CONTEXT
    query: str = ''
    thought: str = ''
    action: ClassVar[str] = ActionType.RECALL

    @property
    def message(self) -> str:
        """Get recall query message."""
        return f'Retrieving content for: {self.query[:50]}'

    def __str__(self) -> str:
        """Return a concise representation showing the recall query."""
        ret = '**RecallAction**\n'
        ret += f'QUERY: {self.query[:50]}'
        return ret


@dataclass
class CondensationAction(Action):
    """This action indicates a condensation of the conversation history is happening.

    There are two ways to specify the events to be pruned:
    1. By providing a list of event IDs.
    2. By providing the start and end IDs of a range of events.

    In the second case, we assume that event IDs are monotonically increasing, and that _all_ events between the start and end IDs are to be pruned.

    Raises:
        ValueError: If the optional fields are not instantiated in a valid configuration.

    """

    action: ClassVar[str] = ActionType.CONDENSATION
    pruned_event_ids: list[int] | None = None
    'The IDs of the events that are being pruned (removed from the `View` given to the LLM).'
    pruned_events_start_id: int | None = None
    'The ID of the first event to be pruned in a range of events.'
    pruned_events_end_id: int | None = None
    'The ID of the last event to be pruned in a range of events.'
    summary: str | None = None
    'An optional summary of the events being pruned.'
    summary_offset: int | None = None
    'An optional offset to the start of the resulting view indicating where the summary should be inserted.'
    is_prewarmed: bool = False
    'Indicates if this condensation was generated proactively in the background.'

    def _validate_field_polymorphism(self) -> bool:
        """Check if the optional fields are instantiated in a valid configuration."""
        using_event_ids = self.pruned_event_ids is not None
        using_event_range = (
            self.pruned_events_start_id is not None
            and self.pruned_events_end_id is not None
        )
        pruned_event_configuration = using_event_ids ^ using_event_range
        summary_configuration = (
            self.summary is None and self.summary_offset is None
        ) or (self.summary is not None and self.summary_offset is not None)
        return pruned_event_configuration and summary_configuration

    def __post_init__(self):
        """Validate that the provided fields describe exactly one pruning strategy."""
        if not self._validate_field_polymorphism():
            msg = 'Invalid configuration of the optional fields.'
            raise ValueError(msg)

    @property
    def pruned(self) -> list[int]:
        """The list of event IDs that should be pruned."""
        if not self._validate_field_polymorphism():
            msg = 'Invalid configuration of the optional fields.'
            raise ValueError(msg)
        if self.pruned_event_ids is not None:
            return self.pruned_event_ids
        assert self.pruned_events_start_id is not None
        assert self.pruned_events_end_id is not None
        return list(range(self.pruned_events_start_id, self.pruned_events_end_id + 1))

    @property
    def message(self) -> str:
        """Get condensation summary or event list message."""
        if self.summary:
            return f'Summary: {self.summary}'
        return f'Compactor is dropping the events: {self.pruned}.'


@dataclass
class CondensationRequestAction(Action):
    """This action is used to request a condensation of the conversation history.

    Attributes:
        action (str): The action type, namely ActionType.CONDENSATION_REQUEST.

    """

    action: ClassVar[str] = ActionType.CONDENSATION_REQUEST

    @property
    def message(self) -> str:
        """Get condensation request message."""
        return 'Requesting a condensation of the conversation history.'


@dataclass
class AcceptanceCriteriaAction(Action):
    """An action where the agent writes or audits flat acceptance criteria.

    Attributes:
        command (str): One of view, update, append, audit.
        criteria_list (list): Flat list of verifiable assertion dicts.
        thought (str): The agent's explanation of its actions.
    """

    command: str = 'view'
    criteria_list: list[dict[str, Any]] = field(default_factory=list)
    thought: str = ''
    action: ClassVar[str] = ActionType.ACCEPTANCE_CRITERIA

    @property
    def message(self) -> str:
        """Get acceptance criteria message with count."""
        num = len(self.criteria_list)
        if num == 0:
            return 'Viewing acceptance criteria.'
        if num == 1:
            return 'Managing 1 acceptance criterion.'
        return f'Managing {num} acceptance criteria.'


@dataclass
class TaskTrackingAction(Action):
    """An action where the agent writes or updates a task list for task management.

    Attributes:
        task_list (list): The list of task items with their status and metadata.
        thought (str): The agent's explanation of its actions.
        action (str): The action type, namely ActionType.TASK_TRACKING.

    """

    command: str = 'view'
    task_list: list[dict[str, Any]] = field(default_factory=list)
    thought: str = ''
    action: ClassVar[str] = ActionType.TASK_TRACKING

    @property
    def message(self) -> str:
        """Get task tracking message with count."""
        num_tasks = len(self.task_list)
        if num_tasks == 0:
            return 'Clearing the task list.'
        if num_tasks == 1:
            return 'Managing 1 task item.'
        return f'Managing {num_tasks} task items.'


# ============================================================================
# Meta-cognition actions - enabling the LLM to express uncertainty and seek guidance
# ============================================================================


@dataclass
class UncertaintyAction(Action):
    """An action where the agent expresses uncertainty about its current understanding or observations.

    This enables the LLM to explicitly flag doubt rather than guessing or hallucinating.
    The system can then provide clarification, additional context, or switch strategy.

    Attributes:
        uncertainty_level (float): Confidence level 0.0-1.0 (1.0 = fully confident)
        specific_concerns (list): Specific things the agent is uncertain about
        requested_information (str): What information would help resolve uncertainty
        thought (str): The agent's explanation of its concerns
        action (str): The action type, namely ActionType.UNCERTAINTY

    """

    uncertainty_level: float = 0.5
    specific_concerns: list[str] = field(default_factory=list)
    requested_information: str = ''
    thought: str = ''
    action: ClassVar[str] = ActionType.UNCERTAINTY

    @property
    def message(self) -> str:
        """Get uncertainty expression message."""
        if self.thought:
            return f'Expressing uncertainty: {self.thought}'
        concerns = (
            ', '.join(self.specific_concerns)
            if self.specific_concerns
            else 'general uncertainty'
        )
        return f'Uncertainty ({self.uncertainty_level:.0%} confidence): {concerns}'


@dataclass
class ProposalAction(Action):
    """An action where the agent proposes options before committing to a path.

    This enables the LLM to suggest different approaches and get user feedback
    before executing potentially risky or irreversible actions.

    Attributes:
        options (list): List of proposed options with pros/cons
        recommended (int): Index of the recommended option
        rationale (str): Why these options are being proposed
        thought (str): The agent's explanation
        action (str): The action type, namely ActionType.PROPOSAL

    """

    options: list[dict[str, Any]] = field(default_factory=list)
    recommended: int = 0
    rationale: str = ''
    thought: str = ''
    action: ClassVar[str] = ActionType.PROPOSAL

    @property
    def message(self) -> str:
        """Get proposal message."""
        if self.rationale:
            return f'Proposing options: {self.rationale}'
        return f'Proposing {len(self.options)} options for consideration'


@dataclass
class ClarificationRequestAction(Action):
    """An action where the agent asks for clarification before proceeding.

    This enables the LLM to proactively request clarification rather than
    making assumptions that may lead to errors.

    Attributes:
        question (str): The clarification question
        options (list): Optional multiple choice options. Each entry is a plain
            label, or a dict ``{"label": str, "description": str}``.
        context (str): Why clarification is needed
        thought (str): The agent's reasoning
        action (str): The action type, namely ActionType.CLARIFICATION

    """

    question: str = ''
    options: list[str] = field(default_factory=list)
    context: str = ''
    thought: str = ''
    action: ClassVar[str] = ActionType.CLARIFICATION

    @property
    def message(self) -> str:
        """Get clarification request message."""
        return f'Requesting clarification: {self.question}'


@dataclass
class ConfirmRequestAction(Action):
    """An action where the agent requires explicit user OK before a risky step.

    Used for destructive or irreversible actions. The orchestrator pauses
    until the user picks one of the two options. A configurable default
    (``config.communicate_confirm_timeout_seconds``) auto-denies if the
    user does not respond in time.

    Attributes:
        question (str): What is being asked, e.g. "Delete the user table?"
        options (list): Exactly two options: positive ("Yes, do it") then
            negative ("No, abort"). Each may be a label or a
            ``{"label": str, "description": str}`` dict.
        default_index (int): 0 = auto-confirm on timeout, 1 = auto-deny.
            Defaults to 1 (safe default).
        context (str): Why this is needed; shown under the prompt.
        thought (str): The agent's reasoning.
        action (str): The action type, namely ActionType.CONFIRM.

    """

    question: str = ''
    options: list[str] = field(default_factory=list)
    default_index: int = 1
    context: str = ''
    thought: str = ''
    action: ClassVar[str] = ActionType.CONFIRM

    @property
    def message(self) -> str:
        """Get confirm request message."""
        return f'Confirm required: {self.question}'


@dataclass
class InformAction(Action):
    """A non-blocking status update from the agent to the user.

    The orchestrator does NOT pause for this. The user sees the message in
    the transcript but the agent continues with the next turn immediately.

    Attributes:
        text (str): The update to share.
        context (str): Optional background.
        thought (str): The agent's reasoning.
        action (str): The action type, namely ActionType.INFORM.

    """

    text: str = ''
    context: str = ''
    thought: str = ''
    action: ClassVar[str] = ActionType.INFORM

    @property
    def message(self) -> str:
        """Get the user-facing message."""
        return self.text if self.text else 'Status update'


@dataclass
class EscalateToHumanAction(Action):
    """An action where the agent requests escalation to human assistance.

    This enables the LLM to explicitly request help when it's stuck,
    has tried multiple approaches without success, or needs human intervention.

    Attributes:
        reason (str): Why escalation is being requested
        attempts_made (list): Summary of approaches already tried. Each entry
            is either a plain string (legacy) or a dict with ``action`` /
            ``result`` keys for richer escalation cards.
        specific_help_needed (str): What kind of help is needed
        thought (str): The agent's explanation
        action (str): The action type, namely ActionType.ESCALATE

    """

    reason: str = ''
    attempts_made: list[str] = field(default_factory=list)
    specific_help_needed: str = ''
    thought: str = ''
    action: ClassVar[str] = ActionType.ESCALATE

    @property
    def message(self) -> str:
        """Get escalation message."""
        return f'Requesting human assistance: {self.reason}'


@dataclass
class DelegateTaskAction(Action):
    """An action where the orchestrator delegates a subtask to a worker agent.

    Attributes:
        task_description (str): What the worker should do.
        files (list[str]): Relevant files for the task.
        parallel_tasks (list[dict]): If non-empty, spawn multiple workers concurrently.
            Each item should have 'task_description' and optionally 'files'.
            When present, task_description/files on the parent action are ignored.
        run_in_background (bool): If True, worker runs asynchronously and parent continues.
        depth (int): Current delegation depth (0 = parent, 1 = first-level worker, etc.).
            Used to prevent infinite recursion. Max depth is MAX_DELEGATION_DEPTH.
    """

    task_description: str = ''
    files: list[str] = field(default_factory=list)
    parallel_tasks: list[dict] = field(default_factory=list)
    run_in_background: bool = False
    depth: int = 0
    action: ClassVar[str] = ActionType.DELEGATE_TASK

    @property
    def message(self) -> str:
        """Get delegation message."""
        bg = ' (background)' if self.run_in_background else ''
        return f'Delegating task{bg}: {self.task_description[:50]}...'


@dataclass
class BlackboardAction(Action):
    """Read or write the shared blackboard when running as a delegated worker.

    Used only when delegate_task_blackboard_enabled is True and this agent
    is a sub-agent; the blackboard is shared across parallel workers.
    """

    command: str = 'get'  # get | set | keys
    key: str = ''
    value: str = ''
    action: ClassVar[str] = ActionType.BLACKBOARD
    runnable: ClassVar[bool] = True

    @property
    def message(self) -> str:
        """Get human-readable message."""
        if self.command == 'set':
            return f'Blackboard set {self.key}'
        if self.command == 'keys':
            return 'Blackboard keys'
        return f'Blackboard get {self.key or "all"}'
