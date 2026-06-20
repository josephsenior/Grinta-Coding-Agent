"""Compactor that converts history into structured summaries using template-driven rules."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass
from backend.context.compactor.compactor import BaseLLMCompactor, Compaction
from backend.context.view import View
from backend.core.logging.logger import app_logger as logger
from backend.core.message import Message, TextContent
from backend.ledger.event import Event
from backend.ledger.observation.agent import AgentCondensationObservation

if TYPE_CHECKING:
    pass


class FileModification(BaseModel):
    """A file that was created, modified, or deleted."""

    path: str = Field(description='Absolute file path.')
    change_type: str = Field(
        description='One of: "created", "modified", "deleted".',
    )


class FailedCommand(BaseModel):
    """A command that failed with a non-zero exit code."""

    command: str = Field(description='The exact command that was run.')
    exact_error: str = Field(description='The exact error message or stderr output.')
    exit_code: int = Field(description='The non-zero exit code.')


class CommandResult(BaseModel):
    """A command and its outcome."""

    command: str = Field(description='The exact command that was run.')
    exit_code: int = Field(description='The exit code (0 = success).')
    output_summary: str = Field(
        description='First ~200 chars of stdout/stderr output.',
    )


class Dependency(BaseModel):
    """A dependency or package that was added or modified."""

    name: str = Field(description='Package or module name.')
    version: str = Field(description='Version string or "latest".')


def _strip_title(schema_obj: dict[str, Any]) -> dict[str, Any]:
    """Remove 'title' keys from a JSON schema object (LLMs don't need them)."""
    result = {k: v for k, v in schema_obj.items() if k != 'title'}
    if 'items' in result and isinstance(result['items'], dict):
        result['items'] = _strip_title(result['items'])
    if 'properties' in result and isinstance(result['properties'], dict):
        result['properties'] = {
            k: _strip_title(v) for k, v in result['properties'].items()
        }
    return result


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
    latest_user_request: str = Field(
        default='',
        description='The most recent explicit user request or correction that is still active.',
    )
    current_working_step: str = Field(
        default='',
        description='The exact next step the agent was about to perform before compaction.',
    )
    current_state: str = Field(
        default='',
        description='Current variables, data structures, or other relevant state information.',
    )
    files_modified: list[FileModification] = Field(
        default_factory=list,
        description='Files created, modified, or deleted. Each entry must have absolute path and change_type.',
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
    error_messages: list[FailedCommand] = Field(
        default_factory=list,
        description='Commands that failed. Each entry must have command, exact_error, and exit_code.',
    )
    exact_commands_and_results: list[CommandResult] = Field(
        default_factory=list,
        description='Important commands and their outcomes. Each entry must have command, exit_code, and output_summary.',
    )
    verification_status: str = Field(
        default='',
        description='What has been verified, what failed verification, and what still needs to be rerun.',
    )
    known_failures_or_avoid: str = Field(
        default='',
        description='Specific failed approaches, user rejected approaches, and constraints that must not be repeated.',
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
    dependencies: list[Dependency] = Field(
        default_factory=list,
        description='Dependencies added or modified. Each entry must have name and version.',
    )
    other_relevant_context: str = Field(
        default='',
        description="Any other important information that doesn't fit into the categories above.",
    )
    canonical_active_plan: str = Field(
        default='',
        description='Canonical-state patch: concise active plan that remains valid after compaction.',
    )
    canonical_next_action: str = Field(
        default='',
        description='Canonical-state patch: exact next action the agent should take after compaction.',
    )
    canonical_blockers: str = Field(
        default='',
        description='Canonical-state patch: newline-separated unresolved blockers only; omit stale blockers.',
    )
    canonical_decisions: str = Field(
        default='',
        description='Canonical-state patch: newline-separated durable decisions that affect future work.',
    )
    canonical_invalidated_assumptions: str = Field(
        default='',
        description='Canonical-state patch: newline-separated assumptions proven false or rejected by the user.',
    )
    canonical_active_files: str = Field(
        default='',
        description='Canonical-state patch: newline-separated file paths still relevant to the task.',
    )
    narrative_summary: str = Field(
        default='',
        description='Optional short narrative summary. This is secondary to the canonical-state patch.',
    )

    @classmethod
    def tool_description(cls) -> dict[str, Any]:
        """Description of a tool whose arguments are the fields of this class.

        Can be given to an LLM to force structured generation.
        Uses Pydantic's JSON schema generation for correct nested model schemas.
        """
        schema = cls.model_json_schema()
        # Strip top-level metadata that OpenAI/function-calling APIs reject.
        defs = schema.get('$defs', schema.get('definitions', {}))
        props = schema.get('properties', {})

        # Strip 'title' keys from properties and nested defs (LLMs don't need them).
        cleaned_props: dict[str, Any] = {}
        for name, prop in props.items():
            cleaned_props[name] = _strip_title(prop)
        cleaned_defs: dict[str, Any] = {}
        for name, defn in defs.items():
            cleaned_defs[name] = _strip_title(defn)

        result: dict[str, Any] = {
            'type': 'function',
            'function': {
                'name': 'create_state_summary',
                'description': (
                    'Creates a comprehensive summary of the current state of the '
                    'interaction to preserve context when history grows too large. '
                    'You must include non-empty values for original_objective, '
                    'user_context, completed_tasks, and pending_tasks. '
                    'For files_modified, error_messages, exact_commands_and_results, '
                    'and dependencies you MUST return structured arrays with the '
                    'exact field names specified in the schema — do NOT write '
                    'free-text summaries for these fields.'
                ),
                'parameters': {
                    'type': 'object',
                    'properties': cleaned_props,
                    'required': [
                        'original_objective',
                        'user_context',
                        'completed_tasks',
                        'pending_tasks',
                    ],
                },
            },
        }
        if cleaned_defs:
            result['function']['parameters']['definitions'] = cleaned_defs
        return result

    def __str__(self) -> str:
        """Format the state summary in a clear way for Claude 3.7 Sonnet."""
        files_str = (
            '\n'.join(
                f'  - {fm.path} ({fm.change_type})' for fm in self.files_modified
            )
            or '(none)'
        )
        errors_str = (
            '\n'.join(
                f'  - {fc.command}: {fc.exact_error} (exit={fc.exit_code})'
                for fc in self.error_messages
            )
            or '(none)'
        )
        commands_str = (
            '\n'.join(
                f'  - {cr.command} → exit={cr.exit_code}: {cr.output_summary}'
                for cr in self.exact_commands_and_results
            )
            or '(none)'
        )
        deps_str = (
            '\n'.join(
                f'  - {dep.name}@{dep.version}' for dep in self.dependencies
            )
            or '(none)'
        )
        sections = [
            '# State Summary',
            '## Core Information',
            f'**Original Objective**: {self.original_objective}',
            f'**User Context**: {self.user_context}',
            f'**Completed Tasks**: {self.completed_tasks}',
            f'**Pending Tasks**: {self.pending_tasks}',
            f'**Latest User Request**: {self.latest_user_request}',
            f'**Current Working Step**: {self.current_working_step}',
            f'**Current State**: {self.current_state}',
            '## Code Changes',
            f'**Files Modified**:\n{files_str}',
            f'**Function Changes**: {self.function_changes}',
            f'**Data Structures**: {self.data_structures}',
            f'**Dependencies**:\n{deps_str}',
            '## Testing Status',
            f'**Tests Written**: {self.tests_written}',
            f'**Tests Passing**: {self.tests_passing}',
            f'**Failing Tests**: {self.failing_tests}',
            f'**Error Messages**:\n{errors_str}',
            f'**Exact Commands And Results**:\n{commands_str}',
            f'**Verification Status**: {self.verification_status}',
            f'**Known Failures Or Avoid**: {self.known_failures_or_avoid}',
            '## Version Control',
            f'**Branch Created**: {self.branch_created}',
            f'**Branch Name**: {self.branch_name}',
            f'**Commits Made**: {self.commits_made}',
            f'**PR Created**: {self.pr_created}',
            f'**PR Status**: {self.pr_status}',
            '## Additional Context',
            f'**Other Relevant Context**: {self.other_relevant_context}',
            '## Canonical State Patch',
            f'**Active Plan**: {self.canonical_active_plan}',
            f'**Next Action**: {self.canonical_next_action}',
            f'**Blockers**: {self.canonical_blockers}',
            f'**Decisions**: {self.canonical_decisions}',
            f'**Invalidated Assumptions**: {self.canonical_invalidated_assumptions}',
            f'**Active Files**: {self.canonical_active_files}',
            f'**Narrative Summary**: {self.narrative_summary}',
        ]
        return '\n\n'.join(sections)

    def canonical_patch(self) -> dict[str, Any]:
        """Return the low-authority canonical-state enrichment patch."""
        narrative = self.narrative_summary or '\n'.join(
            part
            for part in (
                self.user_context,
                self.completed_tasks,
                self.pending_tasks,
                self.other_relevant_context,
            )
            if part
        )
        return {
            'active_plan': self.canonical_active_plan or self.pending_tasks,
            'next_action': self.canonical_next_action or self.current_working_step,
            'blockers': self.canonical_blockers or self.known_failures_or_avoid,
            'decisions': self.canonical_decisions,
            'invalidated_assumptions': self.canonical_invalidated_assumptions,
            'active_files': self.canonical_active_files
            or '\n'.join(fm.path for fm in self.files_modified),
            'narrative_summary': narrative[:1200],
            'vcs_status': self._vcs_status_patch(),
        }

    def _vcs_status_patch(self) -> str:
        parts = []
        if self.branch_name:
            parts.append(f'branch={self.branch_name}')
        if self.branch_created:
            parts.append(f'branch_created={self.branch_created}')
        if self.commits_made:
            parts.append(f'commits_made={self.commits_made}')
        if self.pr_created:
            parts.append(f'pr_created={self.pr_created}')
        if self.pr_status:
            parts.append(f'pr_status={self.pr_status}')
        return '; '.join(parts)


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

    async def get_compaction(self, view: View) -> Compaction:
        """Generate condensation from view by summarizing pruned events.

        If the LLM call fails (network, rate-limit, provider outage), fall
        back to a non-LLM degraded summary so the agent can keep running
        instead of hard-stalling on context pressure.
        """
        # Prepare view sections
        _head, pruned_events, summary_event = self._prepare_view_sections(view)
        if not pruned_events:
            return self._create_compaction_result(pruned_events, '')

        # Build prompt for LLM
        prompt = self._build_condensation_prompt(summary_event, pruned_events)

        self.last_state_patch: dict[str, Any] = {}
        self.last_degraded = False

        # Get summary from LLM, with degraded fallback
        try:
            summary = await self._get_llm_summary(prompt)
            self.last_state_patch = summary.canonical_patch()
            summary_text = str(summary)
        except Exception as e:
            self.last_degraded = True
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

        # Get pruned events (exclude summary events). Build the stop index
        # explicitly so tail_count=0 means "through the end", not slice stop 0.
        tail_count = max(0, events_from_tail)
        stop = len(view) - tail_count if tail_count else len(view)
        pruned_slice = view[self.keep_first : stop]
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
            'Your tool output has two layers:\n'
            '- Regular narrative fields for human-readable continuity.\n'
            '- canonical_* fields that form a compact canonical-state patch. These must contain only current, still-valid facts. Do not repeat stale failed approaches, old test statuses, or generic "resuming task" boilerplate.\n\n'
            'You will be given:\n'
            '- A list of events (actions taken by the agent)\n'
            '- The most recent previous summary (if one exists)\n\n'
            'Capture all relevant information, especially:\n'
            '- The verbatim original user objective (this is non-negotiable)\n'
            '- User requirements that were explicitly stated\n'
            '- The latest user correction/request if it changed the task direction\n'
            '- Work that has been completed\n'
            '- Tasks that remain pending\n'
            '- The immediate next step the agent should take after compaction\n'
            '- Exact file paths, commands, test names, failing assertions, and provider errors\n'
            '- Explicit approaches the user rejected or asked not to repeat\n'
            '- Current state of code, variables, and data structures\n'
            '- The status of any version control operations\n\n'
            'STRUCTURED FIELDS — you MUST return these as typed arrays, not free text:\n'
            '- files_modified: list of {path, change_type} objects with absolute paths\n'
            '- error_messages: list of {command, exact_error, exit_code} objects\n'
            '- exact_commands_and_results: list of {command, exit_code, output_summary} objects\n'
            '- dependencies: list of {name, version} objects\n\n'
            'For canonical_next_action, write one concrete next action. For canonical_active_files, include only paths still relevant to upcoming work. For canonical_blockers, include only unresolved blockers.\n\n'
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

    async def _get_llm_summary(self, prompt: str) -> StateSummary:
        """Get summary from LLM using tool calling."""
        assert self.llm is not None, 'LLM required for structured summary compactor'
        messages = [Message(role='user', content=[TextContent(text=prompt)])]

        response = await self.llm.acompletion(
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
