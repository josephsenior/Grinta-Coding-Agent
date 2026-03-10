from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.controller.state.state import State
    from backend.events.action import Action


class OrchestratorSafetyManager:
    """Encapsulates anti-hallucination pipelines and tool enforcement logic."""

    def __init__(
        self,
        anti_hallucination,
        hallucination_detector,
    ) -> None:
        self._anti_hallucination = anti_hallucination
        self._hallucination_detector = hallucination_detector

    # ------------------------------------------------------------------ #
    # Tool enforcement helpers
    # ------------------------------------------------------------------ #
    def should_enforce_tools(
        self,
        last_user_message: str | None,
        state: State,
        default: str,
    ) -> str:
        if not last_user_message:
            return default

        if not self._anti_hallucination:
            return default

        try:
            return self._anti_hallucination.should_enforce_tools(
                last_user_message,
                state,
                strict_mode=True,
            )
        except Exception:  # pragma: no cover - defensive
            return default

    # ------------------------------------------------------------------ #
    # Action validation pipeline
    # ------------------------------------------------------------------ #
    def apply(
        self, response_text: str, actions: Sequence[Action]
    ) -> tuple[bool, list[Action]]:
        """Run the full safety pipeline on proposed actions.

        Returns:
            Tuple of (continue_processing, updated_actions)
        """
        actions_list = list(actions)
        continue_processing, actions_list = self._pre_validate(response_text, actions_list)
        if not continue_processing:
            return False, actions_list

        actions_list = self._inject_verification(actions_list)
        actions_list = self._detect_and_warn(response_text, actions_list)
        return True, actions_list

    def _pre_validate(
        self,
        response_text: str,
        actions: list[Action],
    ) -> tuple[bool, list[Action]]:
        if not self._anti_hallucination:
            return True, actions

        is_valid, error_msg = self._anti_hallucination.validate_response(
            response_text,
            actions,
        )
        if is_valid:
            return True, actions

        logger.error("🚫 BLOCKED HALLUCINATION: %s", error_msg)
        from backend.events.action import MessageAction

        message = error_msg or "Response blocked by anti-hallucination system."
        # Always return a core MessageAction instance (not a subclass) to avoid
        # cross-module identity issues in tests that assert isinstance(..., MessageAction).
        plain = MessageAction(content=message, wait_for_response=False)
        if type(plain) is not MessageAction:  # pragma: no cover - defensive
            plain = MessageAction(content=str(message), wait_for_response=False)
        return False, [plain]

    def _inject_verification(self, actions: list[Action]) -> list[Action]:
        if not self._anti_hallucination:
            return actions

        self._anti_hallucination.turn_counter += 1
        return self._anti_hallucination.inject_verification_commands(
            actions,
            turn=self._anti_hallucination.turn_counter,
        )

    def _detect_and_warn(
        self,
        response_text: str,
        actions: list[Action],
    ) -> list[Action]:
        if not self._hallucination_detector:
            return actions

        tools_called = self._derive_tools_called(actions)
        detection = self._hallucination_detector.detect_text_hallucination(
            response_text,
            tools_called,
            actions,
        )

        if not self._should_warn_on_detection(detection):
            return actions

        self._log_detection(detection)
        return self._prepend_warning(actions, detection)

    def _derive_tools_called(self, actions: list[Action] | None) -> list[str]:
        tools_called: list[str] = []
        for action in actions or []:
            func_name = self._tool_function_name(action)
            if func_name:
                tools_called.append(func_name)
        return tools_called

    @staticmethod
    def _tool_function_name(action: Action) -> str | None:
        meta = getattr(action, "tool_call_metadata", None)
        if meta and hasattr(meta, "function_name"):
            func_name = getattr(meta, "function_name")
            if isinstance(func_name, str) and func_name.strip():
                return func_name
        func_name = getattr(action, "action", None)
        if isinstance(func_name, str) and func_name.strip():
            return func_name
        return None

    @staticmethod
    def _should_warn_on_detection(detection: dict) -> bool:
        if not detection or not detection.get("hallucinated"):
            return False
        severity = detection.get("severity")
        return severity in {"critical", "high"}

    @staticmethod
    def _log_detection(detection: dict) -> None:
        logger.warning(
            "HALLUCINATION DETECTED: %s severity - Claimed: %s, Missing tools: %s",
            detection.get("severity"),
            detection.get("claimed_operations"),
            detection.get("missing_tools"),
        )

    def _prepend_warning(self, actions: list[Action], detection: dict) -> list[Action]:
        from backend.events.action import MessageAction

        content = self._build_warning_content(
            detection.get("claimed_operations") or [],
            detection.get("missing_tools") or [],
        )
        warning = MessageAction(content=content, wait_for_response=False)
        if type(warning) is not MessageAction:  # pragma: no cover - defensive
            warning = MessageAction(content=str(content), wait_for_response=False)
        actions.insert(0, warning)
        return actions

    @staticmethod
    def _build_warning_content(
        claimed_operations: list[str],
        missing_tools: list[str],
    ) -> str:
        claimed_lines = "\n".join(f"  - {op}" for op in claimed_operations)
        tool_hint = ", ".join(missing_tools) if missing_tools else "str_replace_editor"
        return (
            "⚠️ CRITICAL ERROR — You described operations in plain text but called NO tools:\n"
            + claimed_lines
            + f"\n\nRequired tools that were NOT called: {tool_hint}"
            + "\n\nMANDATORY: Do NOT call 'think'. Do NOT explain what you will do."
            " IMMEDIATELY call str_replace_editor (command=\"create\") for each file."
            " One tool call per file. Start NOW."
        )
