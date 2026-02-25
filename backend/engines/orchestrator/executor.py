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

from backend.core.errors import ModelProviderError
from backend.core.logger import forge_logger as logger
from backend.engines.orchestrator import function_calling as _function_calling_module  # noqa: F401 - ensures module is in sys.modules for the proxy
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


orchestrator_function_calling = _FunctionCallingProxy(
    "backend.engines.orchestrator.function_calling"
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

        # Write-ahead checkpoint before invoking the model.
        #
        # NOTE: Forge's DirectLLMClient implementations intentionally expose
        # deterministic *non-streaming* completion for all providers. Native
        # streaming support varies widely across SDKs and tends to be the
        # source of flakiness. To keep UX responsive without relying on
        # provider-specific streaming, we always fetch a complete response
        # and then emit StreamingChunkAction events derived from the final text.
        ckpt_token = self._checkpoint.begin(params)

        call_params = dict(params)

        try:
            call_params["stream"] = False
            response = self._llm.completion(**call_params)
        except Exception as exc:
            logger.error("Error during LLM completion: %s", exc)
            error_message = str(exc)
            raise ModelProviderError(
                "LLM completion failed",
                context={"error": error_message},
            ) from exc

        if response is None:
            raise ModelProviderError("LLM returned no response")

        # Emit synthetic streaming events from the final response text
        # (post-hoc streaming). This is deterministic and provider-agnostic.
        try:
            if response is not None and event_stream is not None:
                response_text = self._extract_response_text(response)
                if response_text:
                    self._emit_streaming_actions(response_text, event_stream)
        except Exception as exc:  # pragma: no cover - streaming is best-effort
            logger.debug("Failed to emit streaming actions: %s", exc)

        # Commit checkpoint after a successful completion call.
        self._checkpoint.commit(ckpt_token)

        execution_time = time.time() - start_time
        actions = self._response_to_actions(response)
        for action in actions:
            if getattr(action, "action", "") == "message":
                content = getattr(action, "content", "")
                if not str(content).strip():
                    raise ModelProviderError("LLM returned an empty message action")
        return ExecutionResult(actions, response, execution_time, error_message)

    # ------------------------------------------------------------------ #
    # Streaming helpers (provider-agnostic post-hoc streaming)
    # ------------------------------------------------------------------ #
    def _emit_streaming_actions(self, text: str, event_stream: EventStream) -> None:
        from backend.events.action.message import StreamingChunkAction
        from backend.events.event import EventSource

        # Keep event volume bounded. UI-side coalescing exists, but we still
        # avoid emitting thousands of tiny events for long responses.
        chunk_size = 80
        if not text:
            return

        accumulated = ""
        for i in range(0, len(text), chunk_size):
            chunk = text[i : i + chunk_size]
            if not chunk:
                continue
            accumulated += chunk
            ev = StreamingChunkAction(
                chunk=chunk,
                accumulated=accumulated,
                is_final=False,
            )
            ev.source = EventSource.AGENT
            event_stream.add_event(ev, EventSource.AGENT)

        final_ev = StreamingChunkAction(chunk="", accumulated=accumulated, is_final=True)
        final_ev.source = EventSource.AGENT
        event_stream.add_event(final_ev, EventSource.AGENT)

    # ------------------------------------------------------------------ #
    # Response processing
    # ------------------------------------------------------------------ #
    def _response_to_actions(self, response: ModelResponse) -> list[Action]:
        actions = orchestrator_function_calling.response_to_actions(
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
        if not hasattr(choice, "message"):
            return ""
        content = getattr(choice.message, "content", None)
        return self._content_to_str(content)

    def _content_to_str(self, content: Any) -> str:
        """Convert message content (str, list of parts, etc.) to a plain string."""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            text = content.get("text")
            return text if isinstance(text, str) else ""
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item:
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text:
                        parts.append(text)
            return "".join(parts)
        return str(content) if content else ""

    def _extract_last_user_text(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            role = ""
            content: Any = ""
            if isinstance(message, dict):
                role = str(message.get("role", ""))
                content = message.get("content", "")
            else:
                role = str(getattr(message, "role", ""))
                content = getattr(message, "content", "")
            if role != "user":
                continue
            return self._content_to_str(content).strip()
        return ""

    def _extract_recent_user_text(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            role = ""
            content: Any = ""
            if isinstance(message, dict):
                role = str(message.get("role", ""))
                content = message.get("content", "")
            else:
                role = str(getattr(message, "role", ""))
                content = getattr(message, "content", "")
            if role != "user":
                continue
            text = self._content_to_str(content).strip()
            if text:
                return text
        return ""

    
