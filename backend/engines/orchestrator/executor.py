from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    runtime_checkable,
)

from backend.core.logger import forge_logger as logger
from backend.engines.orchestrator.streaming_checkpoint import StreamingCheckpoint

if TYPE_CHECKING:
    from backend.events.action import Action
    from backend.events.stream import EventStream
    from backend.llm.llm import LLM

    from .planner import OrchestratorPlanner
    from .safety import OrchestratorSafetyManager


# ---------------------------------------------------------------------------
# Typed model-response protocol
# ---------------------------------------------------------------------------
@runtime_checkable
class ModelResponse(Protocol):
    """Structural type for LLM completion responses (OpenAI-compatible)."""

    choices: list
    id: str


@dataclass(slots=True)
class ExecutionResult:
    """Container for executor outcomes."""

    actions: list[Action] = field(default_factory=list)
    response: ModelResponse | Any | None = None
    execution_time: float = 0.0
    error: str | None = None


class _FunctionCallingProxy:
    """Proxy that forwards attribute access to the live function_calling module.

    Keeps track of attribute overrides (via monkeypatch) so they persist even if
    the underlying module is reloaded during other tests.
    """

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self._overrides: dict[str, Any] = {}

    @property
    def module(self):
        return sys.modules[self.module_name]

    def __getattr__(self, item):
        if item in self._overrides:
            return self._overrides[item]
        return getattr(self.module, item)

    def __setattr__(self, key, value):
        if key in {"module_name", "_overrides"}:
            object.__setattr__(self, key, value)
        else:
            self._overrides[key] = value
            setattr(self.module, key, value)


codeact_function_calling = _FunctionCallingProxy(
    "forge.engines.orchestrator.function_calling"
)


class OrchestratorExecutor:
    """Handles LLM invocation, streaming, and post-processing."""

    def __init__(
        self,
        llm: LLM,
        safety_manager: OrchestratorSafetyManager,
        planner: OrchestratorPlanner,
        mcp_tool_name_provider: Callable[[], Iterable[str]],
    ) -> None:
        self._llm = llm
        self._safety = safety_manager
        self._planner = planner
        self._mcp_tool_name_provider = mcp_tool_name_provider
        # Write-ahead checkpoint for crash recovery
        ckpt_dir = os.path.join(
            os.environ.get("FORGE_DATA_DIR", os.path.expanduser("~/.forge")),
            "streaming_checkpoints",
        )
        self._checkpoint = StreamingCheckpoint(ckpt_dir)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def execute(
        self,
        params: dict,
        event_stream: EventStream | None,
    ) -> ExecutionResult:
        start_time = time.time()
        error_message: str | None = None
        response: ModelResponse | None = None

        # Write-ahead checkpoint before streaming
        ckpt_token = self._checkpoint.begin(params)

        try:
            accumulated_content, accumulated_chunks = self._stream_llm_response(
                params,
                event_stream,
            )
            response = self._build_final_response(
                accumulated_chunks, accumulated_content
            )
            if response is None:
                logger.warning("Streaming returned None, falling back to non-streaming")
                response = self._fallback_non_streaming(params)
        except Exception as exc:  # pragma: no cover - handled by fallback
            logger.error("Error during streaming: %s", exc)
            error_message = str(exc)
            response = self._fallback_non_streaming(params)

        # Commit checkpoint on success
        self._checkpoint.commit(ckpt_token)

        execution_time = time.time() - start_time
        actions = self._response_to_actions(response) if response is not None else []
        return ExecutionResult(actions, response, execution_time, error_message)

    # ------------------------------------------------------------------ #
    # Streaming helpers
    # ------------------------------------------------------------------ #
    def _stream_llm_response(
        self,
        params: dict,
        event_stream: EventStream | None,
    ) -> tuple[str, list]:
        from backend.events.action.message import StreamingChunkAction
        from backend.events.event import EventSource

        response_stream = self._llm.completion(**params)
        accumulated_content = ""
        accumulated_chunks: list = []

        for chunk in response_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            token = getattr(delta, "content", None)
            if not token:
                continue
            accumulated_content += token
            accumulated_chunks.append(chunk)

            streaming_action = StreamingChunkAction(
                chunk=token,
                accumulated=accumulated_content,
                is_final=False,
            )
            streaming_action.source = EventSource.AGENT
            if event_stream:
                event_stream.add_event(streaming_action, EventSource.AGENT)

        if accumulated_content:
            final_chunk = StreamingChunkAction(
                chunk="",
                accumulated=accumulated_content,
                is_final=True,
            )
            final_chunk.source = EventSource.AGENT
            if event_stream:
                event_stream.add_event(final_chunk, EventSource.AGENT)

        return accumulated_content, accumulated_chunks

    def _build_final_response(
        self, accumulated_chunks: list, accumulated_content: str
    ) -> Any | None:
        from types import SimpleNamespace

        if not accumulated_chunks:
            return None

        final_response = accumulated_chunks[-1]
        final_response.choices[0].delta.content = accumulated_content
        final_response.choices[0].message = SimpleNamespace(
            content=accumulated_content,
            role="assistant",
        )
        return final_response

    def _fallback_non_streaming(self, params: dict) -> Any:
        params = dict(params)
        params["stream"] = False
        try:
            response = self._llm.completion(**params)
        except Exception as exc:  # pragma: no cover - ultimate fallback
            logger.error("Non-streaming fallback failed: %s", exc)
            response = None

        # Some test stubs (e.g., SimpleNamespace) return objects without the expected
        # `.choices[0].message.content` structure. Create a minimal synthetic response
        # so downstream parsing and safety logic can proceed deterministically.
        if response is None or not hasattr(response, "choices"):
            from types import SimpleNamespace

            synthetic_message = SimpleNamespace(content="")
            synthetic_choice = SimpleNamespace(
                message=synthetic_message, delta=SimpleNamespace(content="")
            )
            # Provide a stable id so downstream telemetry attachment works.
            response = SimpleNamespace(id="fallback", choices=[synthetic_choice])
            logger.debug("Created synthetic fallback response with empty content.")
        elif isinstance(response, object) and not getattr(response, "choices", None):
            from types import SimpleNamespace

            synthetic_message = SimpleNamespace(content="")
            synthetic_choice = SimpleNamespace(
                message=synthetic_message, delta=SimpleNamespace(content="")
            )
            response.choices = [synthetic_choice]  # type: ignore[attr-defined]
            if not hasattr(response, "id"):
                setattr(response, "id", "fallback")
            logger.debug("Augmented fallback response with synthetic choice/message.")

        logger.debug("Fallback non-streaming response: %s", response)
        return response

    # ------------------------------------------------------------------ #
    # Response processing
    # ------------------------------------------------------------------ #
    def _response_to_actions(self, response: ModelResponse) -> list[Action]:
        actions = codeact_function_calling.response_to_actions(
            response,
            mcp_tool_names=list(self._mcp_tool_name_provider()),
        )

        response_text = self._extract_response_text(response)
        proceed, validated_actions = self._safety.apply(response_text, actions)
        if not proceed:
            logger.warning("Safety pipeline blocked response (hallucination or validation failure)")
        return validated_actions

    def _extract_response_text(self, response: ModelResponse) -> str:
        if not hasattr(response, "choices") or not response.choices:
            return ""
        choice = response.choices[0]
        if hasattr(choice, "message") and getattr(choice.message, "content", None):
            return choice.message.content or ""
        return ""
