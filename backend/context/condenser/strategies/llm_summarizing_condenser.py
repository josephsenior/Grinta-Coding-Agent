"""Condenser that summarizes history via LLM-generated CondensationAction events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.message import Message, TextContent
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.context.condenser.condenser import BaseLLMCondenser, Condensation
from backend.context.view import View

if TYPE_CHECKING:
    pass


_SUMMARIZING_PROMPT = """\
You are maintaining a context-aware state summary for an interactive agent.
You will be given a list of events corresponding to actions taken by the agent, \
and the most recent previous summary if one exists.
CRITICAL: You MUST strictly enforce that the *original user objective* is always preserved verbatim at the very top of every compressed state summary. Never allow the core goal to be lost or diluted.
If the events being summarized contain ANY task-tracking, you MUST include a \
TASK_TRACKING section to maintain continuity.
When referencing tasks make sure to preserve exact task IDs and statuses.

Track:

ORIGINAL_OBJECTIVE: (Preserve the original user objective verbatim. Do not summarize or dilute it)

USER_CONTEXT: (Preserve essential user requirements, goals, and clarifications in concise form)

TASK_TRACKING: {Active tasks, their IDs and statuses - PRESERVE TASK IDs}

COMPLETED: (Tasks completed so far, with brief results)
PENDING: (Tasks that still need to be done)
CURRENT_STATE: (Current variables, data structures, or relevant state)

For code-specific tasks, also include:
CODE_STATE: {File paths, function signatures, data structures}
TESTS: {Failing cases, error messages, outputs}
CHANGES: {Code edits, variable updates}
DEPS: {Dependencies, imports, external calls}
VERSION_CONTROL_STATUS: {Repository state, current branch, PR status, commit history}

PRIORITIZE:
1. Adapt tracking format to match the actual task type
2. Capture key user requirements and goals
3. Distinguish between completed and pending tasks
4. Keep all sections concise and relevant

SKIP: Tracking irrelevant details for the current task type

Example formats:

For code tasks:
USER_CONTEXT: Fix FITS card float representation issue
COMPLETED: Modified mod_float() in card.py, all tests passing
PENDING: Create PR, update documentation
CODE_STATE: mod_float() in card.py updated
TESTS: test_format() passed
CHANGES: str(val) replaces f"{val:.16G}"
DEPS: None modified
VERSION_CONTROL_STATUS: Branch: fix-float-precision, Latest commit: a1b2c3d

For other tasks:
USER_CONTEXT: Write 20 haikus based on coin flip results
COMPLETED: 15 haikus written for results [T,H,T,H,T,H,T,T,H,T,H,T,H,T,H]
PENDING: 5 more haikus needed
CURRENT_STATE: Last flip: Heads, Haiku count: 15/20
"""


class LLMSummarizingCondenser(BaseLLMCondenser):
    """A condenser that summarizes forgotten events.

    Maintains a condensed history and forgets old events when it grows too large,
    keeping a special summarization event after the prefix that summarizes all previous summarizations
    and newly forgotten events.
    """

    @staticmethod
    def _extract_user_objective(head_events: list) -> str | None:
        """Extract the user's original objective from the kept head events."""
        from backend.ledger.action.message import MessageAction
        from backend.ledger.event import EventSource

        for event in head_events:
            if isinstance(event, MessageAction) and event.source == EventSource.USER:
                content = getattr(event, "content", None)
                if content and isinstance(content, str) and content.strip():
                    return content.strip()
        return None

    def get_condensation(self, view: View) -> View | Condensation:
        """Summarize middle of conversation using LLM while keeping initial/tail events."""
        head = view[: self.keep_first]
        target_size = self.max_size // 2
        events_from_tail = max(1, target_size - len(head) - 1)

        has_summary = len(view) > self.keep_first
        summary_event = (
            view[self.keep_first]
            if has_summary and isinstance(view[self.keep_first], AgentCondensationObservation)
            else AgentCondensationObservation("No events summarized")
        )
        end_index = max(self.keep_first, len(view) - events_from_tail)
        forgotten_events = [
            event
            for event in view[self.keep_first : end_index]
            if not isinstance(event, AgentCondensationObservation)
        ]
        
        if not forgotten_events:
            return view
        prompt = _SUMMARIZING_PROMPT + "\n\n"

        # Inject the user's original objective so the LLM cannot hallucinate it
        user_objective = self._extract_user_objective(list(head))
        if user_objective:
            prompt += (
                "<ORIGINAL_USER_OBJECTIVE>\n"
                f"{self._truncate(user_objective)}\n"
                "</ORIGINAL_USER_OBJECTIVE>\n"
                "CRITICAL: The ORIGINAL_OBJECTIVE field in your summary MUST match the objective above verbatim. "
                "Do NOT invent or substitute a different objective.\n\n"
            )

        summary_event_content = self._truncate(summary_event.message or "")
        prompt += f"<PREVIOUS SUMMARY>\n{summary_event_content}\n</PREVIOUS SUMMARY>\n"
        prompt += "\n\n"
        for forgotten_event in forgotten_events:
            event_content = self._truncate(str(forgotten_event))
            prompt += f"<EVENT id={forgotten_event.id}>\n{event_content}\n</EVENT>\n"
        prompt += "Now summarize the events using the rules above."
        messages = [Message(role="user", content=[TextContent(text=prompt)])]
        assert self.llm is not None, "LLM required for summarizing condenser"
        response = self.llm.completion(
            messages=self.llm.format_messages_for_llm(messages),
            extra_body={"metadata": self.llm_metadata},
        )
        choices = getattr(response, "choices", None)
        if not choices or len(choices) == 0:
            raise ValueError("LLM summarizing condenser received response with no choices")
        summary = choices[0].message.content

        self._add_response_metadata(response)
        return self._create_condensation_result(forgotten_events, summary)


# Lazy registration to avoid circular imports
def _register_config():
    """Register LLMSummarizingCondenserConfig with the LLMSummarizingCondenser factory.

    Defers import of LLMSummarizingCondenserConfig to avoid circular dependency between
    condenser implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate condensers from config objects.

    Side Effects:
        - Imports LLMSummarizingCondenserConfig from backend.core.config.condenser_config
        - Registers config class with LLMSummarizingCondenser.register_config() factory

    Notes:
        - Must be called at module level after LLMSummarizingCondenser class definition
        - Pattern reused across all condenser implementations
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.condenser_config import LLMSummarizingCondenserConfig

    LLMSummarizingCondenser.register_config(LLMSummarizingCondenserConfig)


_register_config()
