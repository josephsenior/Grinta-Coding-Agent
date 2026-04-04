"""Agent-scoped observation types emitted by App event stream."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from backend.persistence.data_models.knowledge_base import KnowledgeBaseSearchResult

from backend.core.enums import RecallType
from backend.core.schemas import AgentState, ObservationType
from backend.ledger.observation.observation import Observation


@dataclass
class AgentStateChangedObservation(Observation):
    """This data class represents an observation of an agent's state change."""

    agent_state: AgentState | str
    reason: str = ''
    observation: ClassVar[str] = ObservationType.AGENT_STATE_CHANGED

    @property
    def message(self) -> str:
        """Get message (empty for state change observations)."""
        return ''


@dataclass
class AgentCondensationObservation(Observation):
    """The output of a condensation action."""

    observation: ClassVar[str] = ObservationType.CONDENSE

    @property
    def message(self) -> str:
        """Get condensation result message."""
        return self.content


@dataclass
class AgentThinkObservation(Observation):
    """The output of a think action.

    In practice, this is a no-op, since it will just reply a static message to the agent
    acknowledging that the thought has been logged.
    """

    observation: ClassVar[str] = ObservationType.THINK

    @property
    def message(self) -> str:
        """Get acknowledgment message."""
        return self.content


@dataclass
class PlaybookKnowledge:
    """Represents knowledge from a triggered playbook.

    Attributes:
        name: The name of the playbook that was triggered
        trigger: The word that triggered this playbook
        content: The actual content/knowledge from the playbook

    """

    name: str
    trigger: str
    content: str


@dataclass
class RecallObservation(Observation):
    """The retrieval of content from a playbook or more playbooks."""

    recall_type: RecallType
    repo_name: str = ''
    repo_directory: str = ''
    repo_branch: str = ''
    repo_instructions: str = ''
    runtime_hosts: dict[str, int] = field(default_factory=dict)
    additional_agent_instructions: str = ''
    date: str = ''
    custom_secrets_descriptions: dict[str, str] = field(default_factory=dict)
    conversation_instructions: str = ''
    working_dir: str = ''
    playbook_knowledge: list[PlaybookKnowledge] = field(default_factory=list)
    knowledge_base_results: list['KnowledgeBaseSearchResult'] = field(
        default_factory=list
    )
    '\n    A list of PlaybookKnowledge objects, each containing information from a triggered playbook.\n\n    Example:\n    [\n        PlaybookKnowledge(\n            name="python_best_practices",\n            trigger="python",\n            content="Always use virtual environments for Python projects."\n        ),\n        PlaybookKnowledge(\n            name="git_workflow",\n            trigger="git",\n            content="Create a new branch for each feature or bugfix."\n        )\n    ]\n    '
    observation: ClassVar[str] = ObservationType.RECALL

    @property
    def message(self) -> str:
        """Get recall completion message based on recall type."""
        return (
            'Added workspace context'
            if self.recall_type == RecallType.WORKSPACE_CONTEXT
            else 'Added playbook knowledge'
        )

    def __str__(self) -> str:
        """Return a readable summary of the recall payload."""
        fields = []
        if self.recall_type == RecallType.WORKSPACE_CONTEXT:
            fields.extend(
                [
                    f'recall_type={self.recall_type}',
                    f'repo_name={self.repo_name}',
                    f'repo_instructions={self.repo_instructions[:20]}...',
                    f'runtime_hosts={self.runtime_hosts}',
                    f'additional_agent_instructions={self.additional_agent_instructions[:20]}...',
                    f'date={self.date}custom_secrets_descriptions={self.custom_secrets_descriptions}',
                    f'conversation_instructions={self.conversation_instructions[:20]}...',
                ],
            )
        else:
            fields.extend([f'recall_type={self.recall_type}'])
        if self.playbook_knowledge:
            fields.extend(
                [
                    f'playbook_knowledge={", ".join([m.name for m in self.playbook_knowledge])}'
                ]
            )
        return f'**RecallObservation**\n{", ".join(fields)}'


@dataclass
class RecallFailureObservation(Observation):
    """Represents a failure to complete a recall request (workspace or knowledge).

    Provides structured fields to help downstream components distinguish recall failures
    from generic errors and clear pending recall actions without altering iteration semantics.
    """

    recall_type: RecallType | None = None
    error_message: str = ''
    observation: ClassVar[str] = ObservationType.RECALL_FAILURE

    @property
    def message(self) -> str:
        return self.error_message or self.content


@dataclass
class DelegateTaskObservation(Observation):
    """Result of a delegated subtask."""

    success: bool = True
    error_message: str = ''
    observation: ClassVar[str] = ObservationType.DELEGATE_TASK_RESULT

    @property
    def message(self) -> str:
        if self.success:
            return f'Delegated task completed: {self.content}'
        return f'Delegated task failed: {self.error_message or self.content}'
