"""Condenser that delegates event prioritization to an LLM with structured output."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    pass
from backend.ledger.action.agent import CondensationAction
from backend.context.condenser.condenser import BaseLLMCondenser, Condensation
from backend.context.view import View

if TYPE_CHECKING:
    pass


class ImportantEventSelection(BaseModel):
    """Utility class for the `LLMAttentionCondenser` that forces the LLM to return a list of integers."""

    ids: list[int]


class LLMAttentionCondenser(BaseLLMCondenser):
    """Rolling condenser strategy that uses an LLM to select the most important events when condensing the history."""

    def _validate_llm(self) -> None:
        """Validate that the LLM supports response_schema."""
        if self.llm is None:
            return
        if not self.llm.features.supports_response_schema:
            msg = "The LLM model must support the 'response_schema' parameter to use the LLMAttentionCondenser."
            raise ValueError(msg)

    def get_condensation(self, view: View) -> Condensation:
        """Get condensation using LLM attention mechanism.

        Args:
            view: View of events to condense

        Returns:
            Condensation result

        """
        target_size = self.max_size // 2
        head_event_ids = [event.id for event in view.events[: self.keep_first]]
        events_from_tail = target_size - len(head_event_ids)

        response_ids = self._get_llm_ranked_ids(view)
        response_ids = self._filter_head_events(
            response_ids, head_event_ids, events_from_tail
        )
        response_ids = self._backfill_recent_events(
            view, response_ids, events_from_tail
        )

        forgotten_ids = [
            event.id
            for event in view
            if event.id not in response_ids and event.id not in head_event_ids
        ]

        return Condensation(
            action=CondensationAction(forgotten_event_ids=forgotten_ids)
        )

    def _get_llm_ranked_ids(self, view: View) -> list:
        """Get event IDs ranked by LLM importance.

        Args:
            view: View of events

        Returns:
            List of ranked event IDs

        """
        message = (
            "You will be given a list of actions, observations, and thoughts from a coding agent.\n"
            "        Each item in the list has an identifier. Please sort the identifiers in order of how important the\n"
            "        contents of the item are for the next step of the coding agent's task, from most important to least\n"
            "        important."
        )

        messages = [
            {"content": message, "role": "user"},
            *[
                {
                    "content": f"<ID>{e.id}</ID>\n<CONTENT>{e.message}</CONTENT>",
                    "role": "user",
                }
                for e in view
            ],
        ]

        assert self.llm is not None, "LLM required for attention condenser"
        response = self.llm.completion(
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "ImportantEventSelection",
                    "schema": ImportantEventSelection.model_json_schema(),
                },
            },
        )

        self.add_metadata("metrics", self.llm.metrics.get())
        choices = getattr(response, "choices", None)
        if not choices or len(choices) == 0:
            raise ValueError("LLM attention condenser received response with no choices")
        return ImportantEventSelection.model_validate_json(
            choices[0].message.content
        ).ids

    def _filter_head_events(
        self, response_ids: list, head_event_ids: list, events_from_tail: int
    ) -> list:
        """Filter out head events and limit to tail size.

        Args:
            response_ids: LLM-ranked IDs
            head_event_ids: IDs of head events to exclude
            events_from_tail: Number of events to keep from tail

        Returns:
            Filtered list of IDs

        """
        return [rid for rid in response_ids if rid not in head_event_ids][
            :events_from_tail
        ]

    def _backfill_recent_events(
        self, view: View, response_ids: list, events_from_tail: int
    ) -> list:
        """Backfill with recent events if needed.

        Args:
            view: View of events
            response_ids: Current list of IDs to keep
            events_from_tail: Target number of events

        Returns:
            Updated list with backfilled events

        """
        for event in reversed(view):
            if len(response_ids) >= events_from_tail:
                break
            if event.id not in response_ids:
                response_ids.append(event.id)
        return response_ids


# Lazy registration to avoid circular imports
def _register_config():
    """Register LLMAttentionCondenserConfig with the LLMAttentionCondenser factory.

    Defers import of LLMAttentionCondenserConfig to avoid circular dependency between
    condenser implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate condensers from config objects.

    Side Effects:
        - Imports LLMAttentionCondenserConfig from backend.core.config.condenser_config
        - Registers config class with LLMAttentionCondenser.register_config() factory

    Notes:
        - Must be called at module level after LLMAttentionCondenser class definition
        - Pattern reused across all condenser implementations (llm_attention, llm_summarizing, etc.)
        - Avoids import-time circular dependency that would occur if config imported at top level

    """
    from backend.core.config.condenser_config import LLMAttentionCondenserConfig

    LLMAttentionCondenser.register_config(LLMAttentionCondenserConfig)


_register_config()
