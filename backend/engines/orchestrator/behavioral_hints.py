"""Behavioral hint generation based on recent assistant interactions."""

from __future__ import annotations


class BehavioralHintsBuilder:
    """Analyzes recent messages to generate behavioral hints for the LLM."""

    def __init__(self, error_learner=None) -> None:
        self._error_learner = error_learner

    def extract_and_build(self, recent_assistant: list) -> list[str]:
        """Extract tool patterns and build behavioral hints."""
        edited_files, error_count, has_test_run, str_replace_count = self._extract_tool_patterns(recent_assistant)
        return self._build_behavioral_hints(
            edited_files, error_count, has_test_run, str_replace_count
        )

    def _extract_tool_patterns(
        self, recent_assistant: list
    ) -> tuple[dict[str, int], int, bool, int]:
        """Extract edit counts, error count, and test-run flag from assistant messages."""
        edited_files: dict[str, int] = {}
        error_count = 0
        has_test_run = False
        str_replace_count = 0

        for msg in recent_assistant:
            tc_list = msg.get("tool_calls", [])
            if not isinstance(tc_list, list):
                continue
            for tc in tc_list:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_raw = fn.get("arguments", "{}")

                if name in ("str_replace_editor", "edit_file", "structure_editor"):
                    path = self._extract_edit_path(args_raw)
                    if path:
                        edited_files[path] = edited_files.get(path, 0) + 1
                    if name == "str_replace_editor":
                        str_replace_count += 1
                elif name in ("execute_bash", "bash"):
                    args_str = str(args_raw).lower()
                    if "pytest" in args_str or "unittest" in args_str:
                        has_test_run = True

            content = str(msg.get("content", ""))
            if "error" in content.lower() or "failed" in content.lower():
                error_count += 1

        return edited_files, error_count, has_test_run, str_replace_count

    def _extract_edit_path(self, args_raw: str | dict) -> str | None:
        """Extract file path from tool call args if it's an edit (not view)."""
        try:
            import json as _json

            args = _json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            path = args.get("path", args.get("file_path", ""))
            return path if path and args.get("command") != "view" else None
        except Exception:
            return None

    def _build_behavioral_hints(
        self, edited_files: dict[str, int], error_count: int, has_test_run: bool, str_replace_count: int
    ) -> list[str]:
        """Build hint strings from detected patterns.

        Includes: repeated edits to same file, many edits without tests,
        multiple errors suggesting strategy change, cross-file impact warnings,
        and think() usage reminders.
        """
        hints: list[str] = []

        for path, count in edited_files.items():
            if count >= 3:
                hints.append(
                    f"You've edited '{path}' {count} times recently — "
                    "use verify_state to confirm line contents before your next edit."
                )
                break

        if str_replace_count >= 2:
            hints.append(
                "You've used str_replace_editor multiple times. Consider switching to "
                "structure_editor (edit_function, rename_symbol) for function/class-level edits — "
                "it targets by symbol name and avoids context-matching issues."
            )

        total_edits = sum(edited_files.values())
        if total_edits >= 4 and not has_test_run:
            hints.append(
                "Multiple file edits without running tests — consider running the relevant test suite to verify changes."
            )

        if error_count >= 3:
            hints.append(
                "Multiple errors detected — consider working_memory(update, hypothesis) "
                "to reassess, or error_patterns(query) for known fixes."
            )

        # Cross-file impact warning: when any file was edited, suggest checking callers
        if edited_files and total_edits >= 2:
            hints.append(
                "You have edited multiple files. If you changed a function or class signature, "
                'use explore_tree_structure(start_entities=["<file>:<Symbol>"], direction="upstream") '
                "to find callers that may need updating."
            )

        # Within-conversation error learning hypotheses
        if self._error_learner is not None:
            learned = self._error_learner.get_hypotheses(max_hints=3)
            hints.extend(learned)

        # Cap total hints to prevent prompt bloat
        return hints[:5]
