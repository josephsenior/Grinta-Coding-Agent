"""Compactor that converts history into structured summaries using template-driven rules."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass
from backend.context.compactor.compactor import BaseLLMCompactor, Compaction
from backend.context.view import View
from backend.core.logger import app_logger as logger
from backend.core.message import Message, TextContent
from backend.ledger.event import Event
from backend.ledger.observation.agent import AgentCondensationObservation

if TYPE_CHECKING:
    pass


class StateSummary(BaseModel):
    """A structured representation summarizing the state of the agent and the task."""

    original_objective: str = Field(
        default='',
        description='The EXACT, VERBATIM original user objective. Do not summarize or dilute it.',
    )
    user_context: str = Field(
        default='',
        description='Essential user requirements, goals, and clarifications in concise form.',
    )
    completed_tasks: str = Field(
        default='', description='List of tasks completed so far with brief results.'
    )
    pending_tasks: str = Field(
        default='', description='List of tasks that still need to be done.'
    )
    current_state: str = Field(
        default='',
        description='Current variables, data structures, or other relevant state information.',
    )
    files_modified: str = Field(
        default='', description='List of files that have been created or modified.'
    )
    function_changes: str = Field(
        default='', description='List of functions that have been created or modified.'
    )
    data_structures: str = Field(
        default='', description='List of key data structures in use or modified.'
    )
    tests_written: str = Field(
        default='',
        description='Whether tests have been written for the changes. True, false, or unknown.',
    )
    tests_passing: str = Field(
        default='',
        description='Whether all tests are currently passing. True, false, or unknown.',
    )
    failing_tests: str = Field(
        default='', description='List of names or descriptions of any failing tests.'
    )
    error_messages: str = Field(
        default='', description='List of key error messages encountered.'
    )
    branch_created: str = Field(
        default='',
        description='Whether a branch has been created for this work. True, false, or unknown.',
    )
    branch_name: str = Field(
        default='', description='Name of the current working branch if known.'
    )
    commits_made: str = Field(
        default='',
        description='Whether any commits have been made. True, false, or unknown.',
    )
    pr_created: str = Field(
        default='',
        description='Whether a pull request has been created. True, false, or unknown.',
    )
    pr_status: str = Field(
        default='',
        description="Status of any pull request: 'draft', 'open', 'merged', 'closed', or 'unknown'.",
    )
    dependencies: str = Field(
        default='',
        description='List of dependencies or imports that have been added or modified.',
    )
    other_relevant_context: str = Field(
        default='',
        description="Any other important information that doesn't fit into the categories above.",
    )

    @classmethod
    def tool_description(cls) -> dict[str, Any]:
        """Description of a tool whose arguments are the fields of this class.

        Can be given to an LLM to force structured generation.
        """
        properties = {}
        for field_name, field in cls.model_fields.items():
            description = field.description or ''
            properties[field_name] = {'type': 'string', 'description': description}
        return {
            'type': 'function',
            'function': {
                'name': 'create_state_summary',
                'description': 'Creates a comprehensive summary of the current state of the interaction to preserve context when history grows too large. You must include non-empty values for original_objective, user_context, completed_tasks, and pending_tasks.',
                'parameters': {
                    'type': 'object',
                    'properties': properties,
                    'required': [
                        'original_objective',
                        'user_context',
                        'completed_tasks',
                        'pending_tasks',
                    ],
                },
            },
        }

    def __str__(self) -> str:
        """Format the state summary in a clear way for Claude 3.7 Sonnet."""
        sections = [
            '# State Summary',
            '## Core Information',
            f'**Original Objective**: {self.original_objective}',
            f'**User Context**: {self.user_context}',
            f'**Completed Tasks**: {self.completed_tasks}',
            f'**Pending Tasks**: {self.pending_tasks}',
            f'**Current State**: {self.current_state}',
            '## Code Changes',
            f'**Files Modified**: {self.files_modified}',
            f'**Function Changes**: {self.function_changes}',
            f'**Data Structures**: {self.data_structures}',
            f'**Dependencies**: {self.dependencies}',
            '## Testing Status',
            f'**Tests Written**: {self.tests_written}',
            f'**Tests Passing**: {self.tests_passing}',
            f'**Failing Tests**: {self.failing_tests}',
            f'**Error Messages**: {self.error_messages}',
            '## Version Control',
            f'**Branch Created**: {self.branch_created}',
            f'**Branch Name**: {self.branch_name}',
            f'**Commits Made**: {self.commits_made}',
            f'**PR Created**: {self.pr_created}',
            f'**PR Status**: {self.pr_status}',
            '## Additional Context',
            f'**Other Relevant Context**: {self.other_relevant_context}',
        ]
        return '\n\n'.join(sections)


class StructuredSummaryCompactor(BaseLLMCompactor):
    """A compactor that summarizes pruned events into structured summaries.

    Maintains a condensed history and prunes old events when it grows too large.
    Uses structured generation via function-calling to produce summaries that
    replace pruned events.
    """

    def _validate_llm(self) -> None:
        """Validate that the LLM supports function calling."""
        if self.llm and not self.llm.is_function_calling_active():
            msg = 'LLM must support function calling to use StructuredSummaryCompactor'
            raise ValueError(msg)

    def get_compaction(self, view: View) -> Compaction:
        """Generate condensation from view by summarizing pruned events.

        If the LLM call fails (network, rate-limit, provider outage), fall
        back to a non-LLM degraded summary so the agent can keep running
        instead of hard-stalling on context pressure.
        """
        # Prepare view sections
        _head, pruned_events, summary_event = self._prepare_view_sections(view)

        # Build prompt for LLM
        prompt = self._build_condensation_prompt(summary_event, pruned_events)

        # Get summary from LLM, with degraded fallback
        try:
            summary = self._get_llm_summary(prompt)
            summary_text = str(summary)
        except Exception as e:
            logger.warning(
                'Condensation LLM call failed (%s: %s); falling back to '
                'degraded summary so the agent can continue.',
                type(e).__name__,
                e,
            )
            summary_text = self._degraded_summary(summary_event, pruned_events, e)

        # Create compaction result
        return self._create_compaction_result(pruned_events, summary_text)

    def _degraded_summary(
        self,
        summary_event: AgentCondensationObservation,
        pruned_events: list[Event],
        error: BaseException,
    ) -> str:
        """Build a non-LLM placeholder summary used when the summarizer fails.

        Preserves the previous summary (if any) and lists the IDs and types of
        the events being pruned so the agent retains a minimal audit trail.
        """
        prior = str(summary_event) if summary_event else ''
        lines: list[str] = [
            '# State Summary (degraded)',
            f'NOTE: condensation summarizer unavailable ({type(error).__name__}). '
            'Pruned events listed by id/type only; re-summarization will be '
            'attempted on the next compaction cycle.',
        ]
        if prior and prior != 'No events summarized':
            lines.append('## Previous Summary')
            lines.append(prior)
        if pruned_events:
            lines.append('## Pruned Events')
            for ev in pruned_events[:200]:  # hard cap to keep this small
                ev_id = getattr(ev, 'id', '?')
                lines.append(f'- {type(ev).__name__} id={ev_id}')
            if len(pruned_events) > 200:
                lines.append(f'- ... and {len(pruned_events) - 200} more')
        return '\n'.join(lines)

    def _prepare_view_sections(
        self, view: View
    ) -> tuple[list[Event], list[Event], AgentCondensationObservation]:
        """Prepare view sections: head, pruned events, and summary event."""
        head = list(view[: self.keep_first])
        target_size = self.max_size // 2
        events_from_tail = target_size - len(head) - 1

        # Get or create summary event
        summary_event: AgentCondensationObservation
        try:
            candidate_event = view[self.keep_first]
        except IndexError:
            candidate_event = None

        if isinstance(candidate_event, AgentCondensationObservation):
            summary_event = candidate_event
        else:
            summary_event = AgentCondensationObservation('No events summarized')

        # Get pruned events (exclude summary events)
        pruned_slice = view[self.keep_first : -events_from_tail]
        pruned_events: list[Event] = [
            event
            for event in pruned_slice
            if not isinstance(event, AgentCondensationObservation)
        ]

        return head, pruned_events, summary_event

    def _build_condensation_prompt(
        self, summary_event: AgentCondensationObservation, pruned_events: list
    ) -> str:
        """Build the prompt for LLM condensation."""
        base_prompt = (
            'You are maintaining a context-aware state summary for an interactive software agent. This summary is critical because it:\n'
            '1. Preserves essential context when conversation history grows too large\n'
            '2. Prevents lost work when the session length exceeds token limits\n'
            '3. Helps maintain continuity across multiple interactions\n\n'
            'CRITICAL: You MUST strictly enforce that the *original user objective* is always preserved verbatim at the very top of every compressed state summary. Never allow the core goal to be lost or diluted.\n\n'
            'You will be given:\n'
            '- A list of events (actions taken by the agent)\n'
            '- The most recent previous summary (if one exists)\n\n'
            'Capture all relevant information, especially:\n'
            '- The verbatim original user objective (this is non-negotiable)\n'
            '- User requirements that were explicitly stated\n'
            '- Work that has been completed\n'
            '- Tasks that remain pending\n'
            '- Current state of code, variables, and data structures\n'
            '- The status of any version control operations\n\n'
        )

        # Add previous summary
        summary_event_content = self._truncate(summary_event.message or '')
        base_prompt += (
            f'<PREVIOUS SUMMARY>\n{summary_event_content}\n</PREVIOUS SUMMARY>\n\n'
        )

        # Add pruned events.
        for pruned_event in pruned_events:
            event_content = self._truncate(str(pruned_event))
            base_prompt += f'<EVENT id={pruned_event.id}>\n{event_content}\n</EVENT>\n'

        return base_prompt

    def _get_llm_summary(self, prompt: str) -> StateSummary:
        """Get summary from LLM using tool calling."""
        assert self.llm is not None, 'LLM required for structured summary compactor'
        messages = [Message(role='user', content=[TextContent(text=prompt)])]

        response = self.llm.completion(
            messages=self.llm.format_messages_for_llm(messages),
            tools=[StateSummary.tool_description()],
            tool_choice={
                'type': 'function',
                'function': {'name': 'create_state_summary'},
            },
        )

        # Parse response
        summary = self._parse_llm_response(response)

        # Add metadata
        self._add_response_metadata(response)

        return summary

    def _parse_llm_response(self, response) -> StateSummary:
        """Parse LLM response to extract StateSummary."""
        try:
            choices = getattr(response, 'choices', None)
            if not choices or len(choices) == 0:
                raise ValueError('LLM response has no choices')
            message = choices[0].message
            if not hasattr(message, 'tool_calls') or not message.tool_calls:
                msg = 'No tool calls found in response'
                raise ValueError(msg)

            summary_tool_call = next(
                (
                    tool_call
                    for tool_call in message.tool_calls
                    if tool_call.function.name == 'create_state_summary'
                ),
                None,
            )
            if not summary_tool_call:
                msg = 'create_state_summary tool call not found'
                raise ValueError(msg)

            args_json = summary_tool_call.function.arguments
            args_dict = json.loads(args_json)
            return StateSummary.model_validate(args_dict)

        except (ValueError, AttributeError, KeyError, json.JSONDecodeError) as e:
            logger.warning(
                'Failed to parse summary tool call: %s. Using empty summary.', e
            )
            return StateSummary()


# Lazy registration to avoid circular imports
def _register_config():
    """Register StructuredSummaryCompactorConfig with the StructuredSummaryCompactor factory.

    Defers import of StructuredSummaryCompactorConfig to avoid circular dependency between
    compactor implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate compactors from config objects.

    Side Effects:
        - Imports StructuredSummaryCompactorConfig from backend.core.config.compactor_config
        - Registers config class with StructuredSummaryCompactor.register_config() factory

    Notes:
        - Must be called at module level after StructuredSummaryCompactor class definition
        - Pattern reused across all compactor implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.compactor_config import StructuredSummaryCompactorConfig

    StructuredSummaryCompactor.register_config(StructuredSummaryCompactorConfig)


_register_config()
