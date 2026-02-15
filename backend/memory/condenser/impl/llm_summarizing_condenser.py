"""Condenser that summarizes history via LLM-generated CondensationAction events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.message import Message, TextContent
from backend.events.observation.agent import AgentCondensationObservation
from backend.memory.condenser.condenser import BaseLLMCondenser, Condensation
from backend.memory.view import View

if TYPE_CHECKING:
    pass


class LLMSummarizingCondenser(BaseLLMCondenser):
    """A condenser that summarizes forgotten events.

    Maintains a condensed history and forgets old events when it grows too large,
    keeping a special summarization event after the prefix that summarizes all previous summarizations
    and newly forgotten events.
    """

    def get_condensation(self, view: View) -> Condensation:
        """Summarize middle of conversation using LLM while keeping initial/tail events."""
        head = view[: self.keep_first]
        target_size = self.max_size // 2
        events_from_tail = target_size - len(head) - 1
        summary_event = (
            view[self.keep_first]
            if isinstance(view[self.keep_first], AgentCondensationObservation)
            else AgentCondensationObservation("No events summarized")
        )
        forgotten_events = [
            event
            for event in view[self.keep_first : -events_from_tail]
            if not isinstance(event, AgentCondensationObservation)
        ]
        prompt = (
            'You are maintaining a context-aware state summary for an interactive agent.\nYou will be given a list of events corresponding to actions taken by the agent, and the most recent previous summary if one exists.\nIf the events being summarized contain ANY task-tracking, you MUST include a TASK_TRACKING section to maintain continuity.\nWhen referencing tasks make sure to preserve exact task IDs and statuses.\n\nTrack:\n\nUSER_CONTEXT: (Preserve essential user requirements, goals, and clarifications in concise form)\n\nTASK_TRACKING: {Active tasks, their IDs and statuses - PRESERVE TASK IDs}\n\nCOMPLETED: (Tasks completed so far, with brief results)\nPENDING: (Tasks that still need to be done)\nCURRENT_STATE: (Current variables, data structures, or relevant state)\n\nFor code-specific tasks, also include:\nCODE_STATE: {File paths, function signatures, data structures}\nTESTS: {Failing cases, error messages, outputs}\nCHANGES: {Code edits, variable updates}\nDEPS: {Dependencies, imports, external calls}\nVERSION_CONTROL_STATUS: {Repository state, current branch, PR status, commit history}\n\nPRIORITIZE:\n1. Adapt tracking format to match the actual task type\n2. Capture key user requirements and goals\n3. Distinguish between completed and pending tasks\n4. Keep all sections concise and relevant\n\nSKIP: Tracking irrelevant details for the current task type\n\nExample formats:\n\nFor code tasks:\nUSER_CONTEXT: Fix FITS card float representation issue\nCOMPLETED: Modified mod_float() in card.py, all tests passing\nPENDING: Create PR, update documentation\nCODE_STATE: mod_float() in card.py updated\nTESTS: test_format() passed\nCHANGES: str(val) replaces f"{val:.16G}"\nDEPS: None modified\nVERSION_CONTROL_STATUS: Branch: fix-float-precision, Latest commit: a1b2c3d\n\nFor other tasks:\nUSER_CONTEXT: Write 20 haikus based on coin flip results\nCOMPLETED: 15 haikus written for results [T,H,T,H,T,H,T,T,H,T,H,T,H,T,H]\nPENDING: 5 more haikus needed\nCURRENT_STATE: Last flip: Heads, Haiku count: 15/20'
            "\n\n"
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
        summary = response.choices[0].message.content

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
