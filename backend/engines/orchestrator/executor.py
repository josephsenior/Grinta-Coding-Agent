from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from types import SimpleNamespace
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

        # Write-ahead checkpoint before invoking the model.
        #
        # NOTE: Forge's DirectLLMClient implementations intentionally expose
        # deterministic *non-streaming* completion for all providers. Native
        # streaming support varies widely across SDKs and tends to be the
        # source of flakiness. To keep UX responsive without relying on
        # provider-specific streaming, we always fetch a complete response
        # and then emit StreamingChunkAction events derived from the final text.
        ckpt_token = self._checkpoint.begin(params)

        tools_for_fallback = None
        call_params = dict(params)

        # Prompt-based tool calling fallback: if the model doesn't support native
        # tool calling but the planner provided tools, convert the message stream
        # into the tag-based function-call format and omit the native `tools=`
        # payload from the provider request.
        if self._should_use_tool_call_fallback(call_params):
            tools_for_fallback = call_params.get("tools")
            call_params = self._prepare_llm_params_for_tool_call_fallback(call_params)

        try:
            call_params["stream"] = False
            response = self._llm.completion(**call_params)
        except Exception as exc:  # pragma: no cover - handled by fallback
            logger.error("Error during LLM completion: %s", exc)
            error_message = str(exc)
            response = self._fallback_non_streaming(params)

        # If we used tag-based tool calling, parse the assistant content back into
        # OpenAI-compatible `tool_calls` so downstream action parsing remains
        # identical.
        if response is not None and tools_for_fallback:
            response = self._apply_tool_call_fallback_to_response(
                response, tools_for_fallback
            )

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
        actions = self._response_to_actions(response) if response is not None else []
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
            synthetic_message = SimpleNamespace(content="")
            synthetic_choice = SimpleNamespace(
                message=synthetic_message, delta=SimpleNamespace(content="")
            )
            # Provide a stable id so downstream telemetry attachment works.
            response = SimpleNamespace(id="fallback", choices=[synthetic_choice])
            logger.debug("Created synthetic fallback response with empty content.")
        elif isinstance(response, object) and not getattr(response, "choices", None):
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
        if hasattr(choice, "message"):
            content = getattr(choice.message, "content", None)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                try:
                    return "".join(
                        str(item.get("text", ""))
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                except Exception:
                    return str(content)
            if content:
                return str(content)
        return ""

    # ------------------------------------------------------------------ #
    # Tool-call fallback (models without native function calling)
    # ------------------------------------------------------------------ #
    def _should_use_tool_call_fallback(self, params: dict[str, Any]) -> bool:
        try:
            tools = params.get("tools")
            if not tools:
                return False
            return not bool(getattr(self._llm, "is_function_calling_active", lambda: True)())
        except Exception:
            return False

    def _prepare_llm_params_for_tool_call_fallback(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        from backend.llm.fn_call_converter import (
            STOP_WORDS,
            convert_fncall_messages_to_non_fncall_messages,
        )

        call_params = dict(params)
        messages = call_params.get("messages", [])
        tools = call_params.get("tools") or []

        try:
            call_params["messages"] = convert_fncall_messages_to_non_fncall_messages(
                messages=messages,
                tools=tools,
                add_in_context_learning_example=True,
            )
        except Exception as exc:
            logger.debug("Tool-call fallback prompt conversion failed: %s", exc)

        # Native tool calling payloads are not supported by these models.
        call_params.pop("tools", None)
        call_params.pop("tool_choice", None)

        # Encourage clean termination after emitting the </function> tag.
        try:
            supports_stop = bool(getattr(self._llm.features, "supports_stop_words", True))
        except Exception:
            supports_stop = True
        if supports_stop:
            existing_stop = call_params.get("stop")
            if existing_stop is None:
                call_params["stop"] = list(STOP_WORDS)
            elif isinstance(existing_stop, list):
                for w in STOP_WORDS:
                    if w not in existing_stop:
                        existing_stop.append(w)
            else:
                call_params["stop"] = [existing_stop, *STOP_WORDS]

        return call_params

    def _apply_tool_call_fallback_to_response(
        self, response: Any, tools: list[dict[str, Any]]
    ) -> Any:
        """Parse tag-based tool calls from assistant content and attach tool_calls."""

        from backend.llm.fn_call_converter import convert_non_fncall_messages_to_fncall_messages

        try:
            if not getattr(response, "choices", None):
                return response
            choice = response.choices[0]
            assistant_msg = getattr(choice, "message", None)
            if assistant_msg is None:
                return response

            content = getattr(assistant_msg, "content", "") or ""
            converted = convert_non_fncall_messages_to_fncall_messages(
                messages=[{"role": "assistant", "content": content}],
                tools=tools,
            )
            if not converted:
                return response
            first = converted[0]
            tool_calls = first.get("tool_calls")
            if not tool_calls:
                return response

            tool_call_objs = []
            for tc in tool_calls:
                fn = tc.get("function") or {}
                fn_obj = SimpleNamespace(
                    name=fn.get("name"),
                    arguments=fn.get("arguments", "{}"),
                )
                tool_call_objs.append(
                    SimpleNamespace(
                        id=tc.get("id"),
                        type=tc.get("type", "function"),
                        function=fn_obj,
                    )
                )

            try:
                setattr(assistant_msg, "content", first.get("content", ""))
                setattr(assistant_msg, "tool_calls", tool_call_objs)
            except Exception:
                # If the SDK message is immutable, best-effort: replace it on the choice.
                choice.message = SimpleNamespace(
                    content=first.get("content", ""),
                    tool_calls=tool_call_objs,
                )

        except Exception as exc:
            logger.debug("Tool-call fallback parse failed: %s", exc)
        return response
