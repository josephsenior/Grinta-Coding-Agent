"""Step readiness guards around circuit breaker and stuck detection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.errors import AgentStuckInLoopError
from backend.core.logger import forge_logger as logger
from backend.core.schemas import AgentState
from backend.events import EventSource
import os

from backend.events.action import FileEditAction, FileWriteAction
from backend.events.observation import ErrorObservation

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext


class StepGuardService:
    """Ensures controller steps are safe w.r.t. circuit breaker and stuck detection."""

    def __init__(self, context: ControllerContext) -> None:
        self._context = context

    async def ensure_can_step(self) -> bool:
        """Return False if circuit breaker/stuck detection block execution."""
        controller = self._context.get_controller()
        # Stuck detection first — it emits targeted recovery messages.
        # Circuit breaker second — it only decides whether to stop the agent.
        if await self._handle_stuck_detection(controller) is False:
            return False
        if await self._check_circuit_breaker(controller) is False:
            return False
        return True

    async def _check_circuit_breaker(self, controller) -> bool | None:
        cb_service = getattr(controller, "circuit_breaker_service", None)
        if not cb_service:
            return True

        result = cb_service.check()
        if not result or not result.tripped:
            return True

        # Circuit breaker only emits 'stop' for stuck detections now.
        # Step guard handles all recovery messaging separately.
        logger.error("Circuit breaker tripped: %s", result.reason)
        error_obs = ErrorObservation(
            content=(
                f"CIRCUIT BREAKER TRIPPED: {result.reason}\n\n"
                f"Action: {result.action.upper()}\n\n"
                f"{result.recommendation}"
            ),
            error_id="CIRCUIT_BREAKER_TRIPPED",
        )
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        target_state = (
            AgentState.STOPPED if result.action == "stop" else AgentState.PAUSED
        )
        await controller.set_agent_state_to(target_state)
        return False

    async def _handle_stuck_detection(self, controller) -> bool:
        stuck_service = getattr(controller, "stuck_service", None)
        if not stuck_service:
            return True

        # Always compute and expose the repetition score for proactive self-correction
        rep_score = stuck_service.compute_repetition_score()
        state = getattr(controller, "state", None)
        if state and hasattr(state, "turn_signals"):
            state.turn_signals.repetition_score = rep_score

        # Recreation auto-finish: if the agent is in a sustained recreation
        # loop (only re-creating existing files, no new ones), auto-finish
        # the task if enough files have been created.  This bypasses the
        # normal stuck-detection → replan → circuit-breaker path because
        # weak models ignore replan directives and the error injection makes
        # things worse.
        if await self._check_recreation_auto_finish(controller):
            return False  # Stop stepping — we finished the task

        if not stuck_service.is_stuck():
            return True

        cb_service = getattr(controller, "circuit_breaker_service", None)
        if cb_service:
            cb_service.record_stuck_detection()

        # Check if we should auto-finish instead of sending another message
        # the agent ignores.
        stuck_count = 0
        if cb_service:
            try:
                raw_count = cb_service.circuit_breaker.stuck_detection_count
                stuck_count = int(raw_count)
            except (TypeError, ValueError, AttributeError):
                stuck_count = 0
        if stuck_count >= 3 and await self._try_auto_finish(controller):
            return False  # Stop stepping — we finished the task

        # Inject a replan directive; let the circuit breaker handle
        # escalation and eventual stopping.
        logger.warning("Stuck detected — injecting replan directive")
        self._inject_replan_directive(controller)
        return True

    @staticmethod
    def _normalize_path(p: str) -> str:
        """Normalize a file path for comparison: strip /workspace/ prefix, collapse separators."""
        p = p.replace("\\", "/").strip("/")
        if p.startswith("workspace/"):
            p = p[len("workspace/"):]
        return p.strip("/")

    @staticmethod
    def _extract_task_files(text: str) -> set[str]:
        """Extract file paths from a task description.

        Handles paths with special characters like [...nextauth] and
        dotfiles like .env.example.
        """
        import re
        # Match paths like src/app/page.tsx, .env.example, [...nextauth]/route.ts
        # Must start with a word char, '/', '[', or '.' (for dotfiles)
        pattern = r'(?<![.\w])[\w./\[\]]+\.(?:py|html|css|js|jsx|ts|tsx|json|txt|md|yaml|yml|toml|cfg|ini|sh|sql|prisma|env|mjs|cjs|svelte|vue|rs|go|java|rb|php|c|cpp|h|hpp|example)\b'
        paths = set(re.findall(pattern, text))
        # Also match dotfiles like .env.example
        dotfiles = set(re.findall(r'(?:^|\s)(\.[\w]+\.[\w]+)', text, re.MULTILINE))
        paths.update(dotfiles)
        # Normalize all paths
        return {p.replace("\\", "/").strip("/").strip() for p in paths if p.strip()}

    @staticmethod
    def _task_requires_non_file_actions(text: str) -> bool:
        """Best-effort check for tasks that require non-file steps.

        Avoids prematurely telling the agent to call finish() when user asks for
        actions like checkpoint, rollback, memory updates, or content mutation.
        """
        lowered = (text or "").lower()
        markers = (
            "checkpoint",
            "rollback",
            "restore",
            "working memory",
            "add a note",
            "remember",
            "update",
            "modify",
            "change",
            "replace",
            "edit",
        )
        return any(m in lowered for m in markers)

    def _inject_replan_directive(self, controller) -> None:
        """Inject a directive that forces the LLM to take real action.

        Uses ErrorObservation (rendered as role='user') so the message actually
        reaches the LLM.  SystemMessageAction is silently dropped by
        _dedupe_system_messages in conversation_memory.
        """
        from backend.events.action import MessageAction

        state = getattr(controller, "state", None)
        history = getattr(state, "history", []) if state else []

        created_files = self._collect_created_files(history)
        task_files, task_text = self._extract_task_files_and_text(history, MessageAction)
        requires_non_file_actions = self._task_requires_non_file_actions(task_text)
        missing = {
            tf for tf in task_files
            if not any(cf == tf or cf.endswith("/" + tf) for cf in created_files)
        }

        msg, planning = self._build_stuck_recovery_message(
            created_files, missing, requires_non_file_actions
        )

        error_obs = ErrorObservation(content=msg, error_id="STUCK_LOOP_RECOVERY")
        controller.event_stream.add_event(error_obs, EventSource.ENVIRONMENT)

        if state and hasattr(state, "set_planning_directive"):
            state.set_planning_directive(planning, source="StepGuardService")

    def _collect_created_files(self, history: list) -> set[str]:
        """Collect normalized paths of files created via FileWrite/FileEdit."""
        created = set()
        for e in history:
            if isinstance(e, (FileWriteAction, FileEditAction)):
                p = getattr(e, "path", "") or ""
                if p:
                    created.add(self._normalize_path(p))
        return created

    def _extract_task_files_and_text(
        self, history: list, message_action_cls
    ) -> tuple[set[str], str]:
        """Extract task file paths and full task text from first user message."""
        task_files: set[str] = set()
        task_text = ""
        for e in history:
            if isinstance(e, message_action_cls) and getattr(e, "source", None) == EventSource.USER:
                text = getattr(e, "content", "") or ""
                if text:
                    task_text = text
                    task_files = self._extract_task_files(text)
                break
        return task_files, task_text

    def _build_stuck_recovery_message(
        self,
        created_files: set[str],
        missing: set[str],
        requires_non_file_actions: bool,
    ) -> tuple[str, str]:
        """Build stuck recovery message and planning directive."""
        created_str = ", ".join(sorted(created_files))
        if created_files and not missing and not requires_non_file_actions:
            return (
                f"STUCK LOOP DETECTED — You are repeating read-only commands without progress.\n"
                f"You have already created these files: {created_str}.\n"
                "All required files are written. Do NOT re-read or re-create them.\n"
                "YOUR VERY NEXT ACTION MUST BE: call finish() to complete the task.\n"
                "Do NOT run any more commands. Just call finish() NOW.",
                "STUCK RECOVERY: All files done. Call finish() now.",
            )
        if created_files and not missing and requires_non_file_actions:
            return (
                f"STUCK LOOP DETECTED — You are repeating actions without progress.\n"
                f"File creation appears complete: {created_str}.\n"
                "But non-file steps remain (for example: update content, checkpoint/rollback, memory note).\n"
                "Do NOT call checkpoint save repeatedly.\n"
                "YOUR VERY NEXT ACTION MUST BE: execute the next unfinished non-file step.\n"
                "Only call finish() after all requested steps are complete.",
                "STUCK RECOVERY: File exists; complete remaining non-file steps, then finish.",
            )
        if created_files and missing:
            missing_str = ", ".join(sorted(missing))
            return (
                f"STUCK LOOP DETECTED — You are repeating read-only commands without progress.\n"
                f"Files ALREADY created (do NOT re-create): {created_str}.\n"
                f"Files STILL MISSING (create these NOW): {missing_str}.\n"
                "YOUR VERY NEXT ACTION MUST BE: create one of the missing files using str_replace_editor command='create_file'.\n"
                "Do NOT run any read command. Create the file immediately.",
                f"STUCK RECOVERY: Create missing files: {missing_str}. No ls/cat.",
            )
        return (
            "STUCK LOOP DETECTED — You are repeating read-only commands without progress.\n"
            "MANDATORY RECOVERY:\n"
            "1. Do NOT run any read command, including str_replace_editor command='view_file'.\n"
            "2. Create the required files using str_replace_editor command='create_file'.\n"
            "3. When all files are created, call finish().\n"
            "YOUR VERY NEXT ACTION MUST BE a file create or edit — nothing else.",
            "STUCK RECOVERY: Create files now. No read commands.",
        )

    async def _check_recreation_auto_finish(self, controller) -> bool:
        """Auto-finish if the agent is in a sustained file recreation loop.

        Checks whether the agent has stopped creating new files and is only
        re-creating existing ones.  If so and enough files have been created,
        auto-finish the task without injecting any error messages.

        Returns True if auto-finish was triggered.
        """
        from backend.events.observation.files import FileEditObservation

        state = getattr(controller, "state", None)
        if not state or not hasattr(state, "history"):
            return False

        # Only check after enough events — give the model time to work.
        # 500 events ≈ 10 minutes, enough for the model to create 16+ files.
        if len(state.history) < 500:
            return False

        # Look at a wide window of recent events for sustained recreation
        recent = state.history[-80:]
        recreate_count = 0
        new_create_count = 0

        for ev in recent:
            if isinstance(ev, FileEditObservation):
                old = getattr(ev, "old_content", None)
                new = getattr(ev, "new_content", None)
                if old is not None and old == new:
                    recreate_count += 1
                elif old is not None or new is not None:
                    new_create_count += 1

        # Only fire if re-creates dominate and few/no new files are being created
        if recreate_count < 8 or new_create_count > 2:
            return False

        logger.warning(
            "Sustained recreation loop: %d re-creates, %d new creates "
            "in last 80 events after %d total events — trying auto-finish",
            recreate_count,
            new_create_count,
            len(state.history),
        )
        return await self._try_auto_finish(controller)

    async def _try_auto_finish(self, controller) -> bool:
        """Auto-finish the task if all expected files are created.

        After multiple stuck detections, the agent has proven it cannot
        follow "call finish()" instructions.  If all task files exist,
        emit a PlaybookFinishAction directly to end the loop.

        Returns True if auto-finish was triggered.
        """
        from backend.events.action import MessageAction
        from backend.events.action.agent import PlaybookFinishAction

        state = getattr(controller, "state", None)
        history = getattr(state, "history", []) if state else []

        # Collect created files (full normalized paths)
        created_files = set()
        for e in history:
            if isinstance(e, (FileWriteAction, FileEditAction)):
                p = getattr(e, "path", "") or ""
                if p:
                    created_files.add(self._normalize_path(p))

        if not created_files:
            return False

        # Extract expected files from the user task (full paths)
        task_files: set[str] = set()
        for e in history:
            if isinstance(e, MessageAction) and getattr(e, "source", None) == EventSource.USER:
                text = getattr(e, "content", "") or ""
                if text:
                    task_files = self._extract_task_files(text)
                break

        if not task_files:
            return False

        # Check missing using suffix matching
        missing = set()
        for tf in task_files:
            if not any(cf == tf or cf.endswith("/" + tf) for cf in created_files):
                missing.add(tf)

        if not missing:
            # All expected files created — auto-finish
            logger.warning(
                "Auto-finishing: all %d task files created, agent stuck",
                len(created_files),
            )
        elif len(created_files) >= len(task_files) * 0.6:
            # At least 60% of files created and agent is stuck in loops —
            # the weak model can't make further progress, so finish with
            # what we have.
            logger.warning(
                "Auto-finishing: %d/%d task files created (%.0f%%), agent stuck",
                len(task_files) - len(missing),
                len(task_files),
                (len(task_files) - len(missing)) / len(task_files) * 100,
            )
        else:
            return False
        finish_action = PlaybookFinishAction(
            thought="All required files have been created. Task complete.",
            outputs={"content": f"Created files: {', '.join(sorted(created_files))}"},
            force_finish=True,
        )
        controller.event_stream.add_event(finish_action, EventSource.AGENT)
        return True
