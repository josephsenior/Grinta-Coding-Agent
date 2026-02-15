"""File verification guard — tool-choice enforcement and auto-verification.

This module:
1. Enforces tool_choice based on user message intent (action vs. question)
2. Injects verification commands after file operations
3. Validates that LLM responses actually call tools when claiming file changes
4. Tracks pending file operations across turns
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger

if TYPE_CHECKING:
    from backend.controller.state.state import State
    from backend.events.action import Action


@dataclass
class FileOperationContext:
    """Tracks ongoing file operations across turns."""

    operation_type: str  # "create", "edit", "delete"
    file_paths: list[str]
    verified: bool = False
    turn_started: int = 0


class FileVerificationGuard:
    """Enforces tool usage and verifies file operations.

    - Determines tool_choice (required/auto) based on user intent
    - Auto-injects verification commands after file edits
    - Validates responses actually call tools when claiming file changes
    - Tracks pending file operations across turns
    """

    def __init__(self):
        """Initialize the anti-hallucination system."""
        self.pending_file_operations: list[FileOperationContext] = []
        self.turn_counter = 0
        self.stats = {
            "verifications_injected": 0,
            "hallucinations_prevented": 0,
            "strict_mode_activations": 0,
        }

    def reset(self) -> None:
        """Reset internal state.

        This is safe to call between tests or user sessions to avoid
        state leaking across runs.
        """
        self.pending_file_operations.clear()
        self.turn_counter = 0
        self.stats = {
            "verifications_injected": 0,
            "hallucinations_prevented": 0,
            "strict_mode_activations": 0,
        }

    def should_enforce_tools(
        self, last_user_message: str, state: State, strict_mode: bool = True
    ) -> str:
        """Determine tool_choice value with AGGRESSIVE enforcement.

        Args:
            last_user_message: The last user message
            state: Current state
            strict_mode: If True, default to "required" instead of "auto"

        Returns:
            "required", "auto", or "none"

        """
        if not last_user_message:
            return "required" if strict_mode else "auto"

        msg_lower = last_user_message.lower()

        # Question patterns - allow text-only (but fewer patterns than before!)
        question_only_patterns = [
            r"^\s*why\s+",
            r"^\s*how does\s+",
            r"^\s*what is\s+",
            r"^\s*explain\s+why\s+",
            r"^\s*tell me why\s+",
        ]

        for pattern in question_only_patterns:
            if re.search(pattern, msg_lower):
                return "auto"  # Pure informational question

        # Action patterns - REQUIRE tools (more comprehensive!)
        action_patterns = [
            r"\bcreate\b",
            r"\bmake\b",
            r"\bwrite\b",
            r"\bedit\b",
            r"\bmodify\b",
            r"\bdelete\b",
            r"\bremove\b",
            r"\bfix\b",
            r"\bimplement\b",
            r"\badd\b",
            r"\bupdate\b",
            r"\bchange\b",
            r"\bbuild\b",
            r"\brun\b",
            r"\binstall\b",
            r"\bset\s+up\b",
            r"\bconfigure\b",
            r"\bdeploy\b",
            r"\brefactor\b",
            r"\brename\b",
            r"\bmove\b",
            r"\bcopy\b",
            r"\btest\b",
            r"\bcheck\b",
        ]

        for pattern in action_patterns:
            if re.search(pattern, msg_lower):
                self.stats["strict_mode_activations"] += 1
                logger.debug("🔒 Enforcing tool usage for action: %s", pattern)
                return "required"  # FORCE tool usage

        # Check if there are pending file operations - require tools for verification
        if self.pending_file_operations:
            logger.debug(
                "🔒 Pending file operations - enforcing tools for verification"
            )
            return "required"

        # STRICT MODE: Default to "required" instead of "auto"
        if strict_mode:
            self.stats["strict_mode_activations"] += 1
            return "required"  # ← Changed from "auto" - this is the key fix!

        return "auto"

    def inject_verification_commands(
        self, actions: list[Action], turn: int
    ) -> list[Action]:
        """Automatically inject verification commands after file operations.

        Args:
            actions: List of actions from LLM
            turn: Current turn number

        Returns:
            Modified actions list with verification commands injected

        """
        enhanced_actions = []

        for action in actions:
            enhanced_actions.append(action)
            if not self._is_file_operation(action):
                continue
            self._append_verification_action(enhanced_actions, action, turn)

        return enhanced_actions

    def _is_file_operation(self, action: Action) -> bool:
        from backend.core.schemas import ActionType

        raw_type = getattr(action, "action", None)
        action_type_values = {
            ActionType.EDIT,
            ActionType.WRITE,
            getattr(ActionType, "EDIT", "edit"),
            getattr(ActionType, "WRITE", "write"),
            "edit",
            "write",
        }
        if raw_type in action_type_values or str(raw_type) in {"edit", "write"}:
            return True

        class_name = type(action).__name__
        if class_name in {"FileEditAction", "FileWriteAction"} and hasattr(
            action, "path"
        ):
            return True

        return bool(
            hasattr(action, "path")
            and isinstance(getattr(action, "path"), str)
            and getattr(action, "path").strip()
        )

    def _append_verification_action(
        self, enhanced_actions: list[Action], action: Action, turn: int
    ) -> None:
        file_path = self._safe_file_path(action)
        if not file_path:
            return
        verification_cmd = self._create_verification_command(file_path)
        if verification_cmd is None:
            return
        self._register_file_operation(file_path, turn)
        enhanced_actions.append(verification_cmd)
        self._record_verification(file_path)

    @staticmethod
    def _safe_file_path(action: Action) -> str | None:
        file_path = getattr(action, "path", None)
        if isinstance(file_path, str) and file_path.strip():
            return file_path
        return None

    def _create_verification_command(self, file_path: str) -> Action | None:
        from backend.events.action import CmdRunAction

        try:
            return CmdRunAction(
                command=f"ls -lah {file_path} && echo '---' && head -20 {file_path}",
                thought=f"[AUTO-VERIFY] Verifying file operation on {file_path}",
            )
        except Exception:  # pragma: no cover - defensive
            return None

    def _register_file_operation(self, file_path: str, turn: int) -> None:
        self.pending_file_operations.append(
            FileOperationContext(
                operation_type="edit",
                file_paths=[file_path],
                verified=False,
                turn_started=turn,
            )
        )

    def _record_verification(self, file_path: str) -> None:
        self.stats["verifications_injected"] += 1
        logger.info("✓ Auto-injected verification for %s", file_path)

    def validate_response(
        self, response_text: str, actions: list[Action]
    ) -> tuple[bool, str | None]:
        """Validate response before returning to user.

        Checks for hallucination patterns and validates tool usage.

        Args:
            response_text: The LLM's text response
            actions: The actions parsed from response

        Returns:
            Tuple of (is_valid, error_message)

        """
        # Check for file operation claims
        file_op_claims = self._extract_file_operation_claims(response_text)

        if file_op_claims:
            # Verify that corresponding tools were called
            from backend.core.schemas import ActionType
            from backend.events.action import CmdRunAction

            has_file_edit = any(
                getattr(a, "action", None) == ActionType.EDIT for a in actions
            )
            has_cmd_run = any(isinstance(a, CmdRunAction) for a in actions)

            if not has_file_edit and not has_cmd_run:
                # Claimed file operation but no tools called!
                error = "⚠️ HALLUCINATION PREVENTED: Response claims file operations but no tools called.\n"
                error += "Claimed operations:\n"
                for claim in file_op_claims:
                    error += f"  - {claim}\n"
                error += "\nYou MUST call the actual tools to perform these operations."

                self.stats["hallucinations_prevented"] += 1
                return False, error

        return True, None

    def _extract_file_operation_claims(self, text: str) -> list[str]:
        """Extract file operation claims from text."""
        claims = []

        # More precise patterns - must have clear file path with extension
        # Avoid matching conversational phrases like "I created a solution"
        patterns = [
            # Match only when followed by actual file paths (with slashes or dots)
            r"I (?:created|wrote|generated|edited|modified|updated|deleted|removed)\s+(?:the\s+file\s+)?[`\"]?(?:[\w\-]+/)+[\w\-]+\.[\w]+[`\"]?",
            r"I've (?:created|written|edited|modified|updated|deleted|removed)\s+(?:the\s+file\s+)?[`\"]?(?:[\w\-]+/)+[\w\-]+\.[\w]+[`\"]?",
            # Match when using backticks or quotes around filename
            r"(?:created|saved|wrote|edited|modified|updated)\s+[`\"][\w\-/]+\.[\w]+[`\"]",
            # Match explicit "to/at/in <file>" patterns
            r"(?:created|saved|wrote)\s+(?:as|to|at|in)\s+[`\"]?(?:[\w\-]+/)+[\w\-]+\.[\w]+[`\"]?",
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                claims.append(match.group(0))

        return list(set(claims))  # Deduplicate

    def mark_operation_verified(self, file_path: str) -> None:
        """Mark a file operation as verified."""
        for op in self.pending_file_operations:
            if file_path in op.file_paths:
                op.verified = True
                logger.debug("✓ Marked %s as verified", file_path)

    def get_unverified_operations(self) -> list[FileOperationContext]:
        """Get list of unverified file operations."""
        return [op for op in self.pending_file_operations if not op.verified]

    def cleanup_old_operations(self, current_turn: int, max_age: int = 3) -> None:
        """Remove old operation contexts."""
        self.pending_file_operations = [
            op
            for op in self.pending_file_operations
            if current_turn - op.turn_started <= max_age
        ]

    def get_stats(self) -> dict:
        """Get system statistics."""
        return {
            **self.stats,
            "pending_operations": len(self.pending_file_operations),
            "unverified_operations": len(self.get_unverified_operations()),
        }
