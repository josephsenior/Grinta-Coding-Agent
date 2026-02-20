"""File verification guard — tool-choice enforcement and auto-verification.

This module:
1. Enforces tool_choice based on user message intent (action vs. question)
2. Injects verification commands after file operations
3. Validates that LLM responses actually call tools when claiming file changes
4. Tracks pending file operations across turns
5. Detects stale reads — forces re-reads when editing files not recently read
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.core.logger import forge_logger as logger

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
            "stale_reads_prevented": 0,
        }
        # Stale-read prevention: track when files were last read and modified
        self._file_read_turns: dict[str, int] = {}
        self._file_modified_turns: dict[str, int] = {}
        self._stale_threshold = 5  # turns before a read is considered stale

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
            "stale_reads_prevented": 0,
        }
        self._file_read_turns.clear()
        self._file_modified_turns.clear()

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

        Also detects stale reads and prepends a re-read before edits on
        files that haven't been read recently or that were modified since
        the last read.

        Args:
            actions: List of actions from LLM
            turn: Current turn number

        Returns:
            Modified actions list with verification commands injected

        """
        enhanced_actions = []

        for action in actions:
            # Stale-read prevention: if this is a file edit and the file
            # hasn't been read recently, inject a read before the edit
            if self._is_file_operation(action):
                file_path = self._safe_file_path(action)
                if file_path and self.is_stale_read(file_path, turn):
                    read_action = self._create_stale_read_action(file_path)
                    if read_action:
                        enhanced_actions.append(read_action)
                        self.record_file_read(file_path, turn)
                        self.stats["stale_reads_prevented"] += 1
                        logger.info(
                            "🔄 Stale-read prevention: forced re-read of %s",
                            file_path,
                        )

            enhanced_actions.append(action)
            if not self._is_file_operation(action):
                continue
            self._append_verification_action(enhanced_actions, action, turn)

        return enhanced_actions

    # ------------------------------------------------------------------ #
    # Stale-read prevention
    # ------------------------------------------------------------------ #

    def record_file_read(self, file_path: str, turn: int) -> None:
        """Record that a file was read at the given turn."""
        self._file_read_turns[file_path] = turn

    def record_file_modification(self, file_path: str, turn: int) -> None:
        """Record that a file was modified at the given turn."""
        self._file_modified_turns[file_path] = turn

    def is_stale_read(self, file_path: str, current_turn: int) -> bool:
        """Check whether the LLM's knowledge of a file is stale.

        A file is considered stale if:
        - It has never been read, OR
        - It was modified after the last read, OR
        - It was last read more than `_stale_threshold` turns ago

        Args:
            file_path: The file path to check
            current_turn: The current turn number

        Returns:
            True if the file content is likely stale in the LLM's context
        """
        last_read = self._file_read_turns.get(file_path)
        last_modified = self._file_modified_turns.get(file_path)

        # Never been read
        if last_read is None:
            return True

        # Modified after last read
        if last_modified is not None and last_modified > last_read:
            return True

        # Read too long ago
        if current_turn - last_read > self._stale_threshold:
            return True

        return False

    def _create_stale_read_action(self, file_path: str) -> Action | None:
        """Create a command to re-read a stale file before editing."""
        from backend.events.action import FileReadAction

        try:
            return FileReadAction(
                path=file_path,
                start=1,
                end=200,
                thought=(
                    f"[STALE-READ PREVENTION] Re-reading {file_path} before edit — "
                    f"file content may have changed since last read."
                ),
            )
        except Exception:  # pragma: no cover - defensive
            return None

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
        from backend.events.action import FileReadAction

        try:
            # Cross-platform, runtime-native verification: re-read a small preview.
            # Deeper checks (existence/line count) are handled in runtime verification.
            return FileReadAction(
                path=file_path,
                start=1,
                end=200,
                thought=f"[AUTO-VERIFY] Re-reading {file_path} after file operation",
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

            has_file_edit = any(
                getattr(a, "action", None) == ActionType.EDIT for a in actions
            )
            has_file_write = any(
                getattr(a, "action", None) == ActionType.WRITE for a in actions
            )
            has_file_read = any(
                getattr(a, "action", None) == ActionType.READ for a in actions
            )

            if not (has_file_edit or has_file_write or has_file_read):
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
            "tracked_reads": len(self._file_read_turns),
            "tracked_modifications": len(self._file_modified_turns),
        }
