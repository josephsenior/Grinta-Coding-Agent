"""LLM-assisted file editing utilities shared across runtime implementations."""

from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Protocol

from backend.core.constants import MAX_LINES_TO_EDIT
from backend.core.logger import app_logger as logger
from backend.ledger.action import (
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.ledger.observation import (
    ErrorObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    Observation,
)
from backend.validation.code_quality import DefaultLinter
from backend.execution.utils.diff import get_diff
from backend.utils.chunk_localizer import Chunk, get_top_k_chunk_matches

if TYPE_CHECKING:
    from backend.core.config import AppConfig
    from backend.inference.llm import LLM
    from backend.inference.llm_registry import LLMRegistry

USER_MSG = "\nCode changes will be provided in the form of a draft. You will need to apply the draft to the original code.\nThe original code will be enclosed within `<original_code>` tags.\nThe draft will be enclosed within `<update_snippet>` tags.\nYou need to output the update code within `<updated_code>` tags.\n\nWithin the `<updated_code>` tag, include only the final code after updation. Do not include any explanations or other content within these tags.\n\n<original_code>{old_contents}</original_code>\n\n<update_snippet>{draft_changes}</update_snippet>\n    "
CORRECT_SYS_MSG = "You are a code repair assistant. Now you have an original file content and error information from a static code checking tool (lint tool). Your task is to automatically modify and return the repaired complete code based on these error messages and refer to the current file content.\n\nThe following are the specific task steps you need to complete:\n\nCarefully read the current file content to ensure that you fully understand its code structure.\n\nAccording to the lint error prompt, accurately locate and analyze the cause of the problem.\n\nModify the original file content and fix all errors prompted by the lint tool.\n\nReturn complete, runnable, and error-fixed code, paying attention to maintaining the overall style and specifications of the original code.\n\nPlease note:\n\nPlease strictly follow the lint error prompts to make modifications and do not miss any problems.\n\nThe modified code must be complete and cannot introduce new errors or bugs.\n\nThe modified code must maintain the original code function and logic, and no changes unrelated to error repair should be made."
CORRECT_USER_MSG = "\nTHE FOLLOWING ARE THE ORIGINAL FILE CONTENTS AND THE ERROR INFORMATION REPORTED BY THE LINT TOOL\n\n# CURRENT FILE CONTENT:\n```\n{file_content}\n```\n\n# ERROR MESSAGE FROM STATIC CODE CHECKING TOOL:\n```\n{lint_error}\n```\n".strip()


def _extract_code(string: str) -> str | None:
    """Extract updated code from LLM response string.

    Args:
        string: The response string containing updated code tags.

    Returns:
        str | None: The extracted code content or None if not found.

    """
    start_tag = "<updated_code>"
    end_tag = "</updated_code>"

    start_idx = string.find(start_tag)
    if start_idx == -1:
        # Fallback to case-insensitive or minor variances if possible
        start_idx = string.lower().find(start_tag)

    if start_idx == -1:
        return None

    start_idx += len(start_tag)
    end_idx = string.lower().find(end_tag, start_idx)
    if end_idx == -1:
        end_idx = len(string)

    content = string[start_idx:end_idx].strip()

    # Strip markdown formatting often returned by models
    if content.startswith("```python"):
        content = content[len("```python"):].lstrip()
    elif content.startswith("```"):
        content = content[len("```"):].lstrip()

    if content.endswith("```"):
        content = content[:-len("```")].rstrip()

    if content.startswith("#EDIT:"):
        content = content[content.find("\n") + 1:]

    return content


def get_new_file_contents(
    llm: LLM, old_contents: str, draft_changes: str, num_retries: int = 3
) -> str | None:
    """Get new file contents using LLM to apply draft changes.

    Args:
        llm: The LLM instance to use for generating code.
        old_contents: The original file contents.
        draft_changes: The draft changes to apply.
        num_retries: Number of retry attempts.

    Returns:
        str | None: The new file contents or None if generation failed.

    """
    while num_retries > 0:
        messages = [
            {
                "role": "user",
                "content": USER_MSG.format(
                    old_contents=old_contents, draft_changes=draft_changes
                ),
            },
        ]
        resp = llm.completion(messages=messages)
        new_contents = _extract_code(resp["choices"][0]["message"]["content"])
        if new_contents is not None:
            return new_contents
        num_retries -= 1
    return None


class FileEditRuntimeInterface(Protocol):
    """Protocol describing minimal read/write/run APIs for runtime editors."""

    async def read(self, path: str) -> str:
        """Read file contents from runtime."""

    async def write(self, action: FileWriteAction) -> Observation:
        """Write file (must be implemented by subclass)."""


class FileEditRuntimeMixin(ABC):
    """Mixin providing LLM-assisted edit flows for runtime implementations."""

    config: AppConfig
    runtime: Any
    draft_editor_llm: LLM | None
    enable_llm_editor: bool

    def __init__(
        self,
        enable_llm_editor: bool,
        llm_registry: LLMRegistry,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Configure LLM-backed editing support before delegating to parent initializers."""
        super().__init__(*args, **kwargs)
        self.enable_llm_editor = enable_llm_editor
        self.draft_editor_llm = None
        if not self.enable_llm_editor:
            return
        draft_editor_config = self.config.get_llm_config("draft_editor")
        if draft_editor_config.caching_prompt:
            logger.debug(
                "It is not recommended to cache draft editor LLM prompts as it may incur high costs for the same prompt. Automatically setting caching_prompt=false.",
            )
            draft_editor_config.caching_prompt = False
        self.draft_editor_llm = llm_registry.get_llm(
            "draft_editor_llm", draft_editor_config
        )
        logger.debug(
            "[Draft edit functionality] enabled with LLM: %s", self.draft_editor_llm
        )

    def _require_draft_editor_llm(self) -> LLM:
        """Return the configured draft editor LLM or raise if unavailable."""
        if self.draft_editor_llm is None:
            raise RuntimeError("LLM-backed editing is disabled for this runtime.")
        return self.draft_editor_llm

    @abstractmethod
    def read(self, action: FileReadAction) -> Observation:
        """Read file contents from the runtime filesystem."""
        raise NotImplementedError

    @abstractmethod
    def write(self, action: FileWriteAction) -> Observation:
        """Write content to a file in the runtime filesystem."""
        raise NotImplementedError

    def _validate_range(
        self, start: int, end: int, total_lines: int
    ) -> Observation | None:
        if (
            (start < 1 and start != -1)
            or start > total_lines
            or (start > end and end != -1 and (start != -1))
        ):
            return ErrorObservation(
                f"Invalid range for editing: start={start}, end={end}, total lines={total_lines}. start must be >= 1 and <={total_lines} (total lines of the edited file), start <= end, or start == -1 (append to the end of the file).",
            )
        if (end < 1 and end != -1) or end > total_lines:
            return ErrorObservation(
                f"Invalid range for editing: start={start}, end={end}, total lines={total_lines}. end must be >= 1 and <= {total_lines} (total lines of the edited file), end >= start, or end == -1 (to edit till the end of the file).",
            )
        return None

    def _get_lint_error(
        self,
        suffix: str,
        old_content: str,
        new_content: str,
        filepath: str,
        diff: str,
    ) -> ErrorObservation | None:
        linter = DefaultLinter()
        with (
            tempfile.NamedTemporaryFile(
                suffix=suffix,
                mode="w+",
                encoding="utf-8",
            ) as original_file_copy,
            tempfile.NamedTemporaryFile(
                suffix=suffix,
                mode="w+",
                encoding="utf-8",
            ) as updated_file_copy,
        ):
            original_file_copy.write(old_content)
            original_file_copy.flush()
            updated_file_copy.write(new_content)
            updated_file_copy.flush()
            updated_lint_error = linter.lint_file_diff(
                original_file_copy.name, updated_file_copy.name
            )

            # If local linter (LSP/Ruff) found nothing, use rigour as a deep fallback for non-Python
            if not updated_lint_error and suffix != ".py":
                # We don't trigger rigour automatically here to avoid latency
                # The agent is encouraged to use it manually via system prompt
                pass

            if updated_lint_error:
                _obs = FileEditObservation(
                    content=diff,
                    path=filepath,
                    prev_exist=True,
                    old_content=old_content,
                    new_content=new_content,
                )
                error_message = (
                    f"\n[Linting failed for edited file {filepath}. {
                        len(updated_lint_error)
                    } lint errors found.]\n[begin attempted changes]\n{
                        _obs.visualize_diff(change_applied=False)
                    }\n[end attempted changes]\n"
                    + "-" * 40
                    + "\n"
                )
                error_message += "-" * 20 + "First 5 lint errors" + "-" * 20 + "\n"
                for i, lint_error in enumerate(updated_lint_error[:5]):
                    error_message += f"[begin lint error {i}]\n"
                    error_message += lint_error.visualize().strip() + "\n"
                    error_message += f"[end lint error {i}]\n"
                    error_message += "-" * 40 + "\n"
                return ErrorObservation(error_message)
        return None

    def _handle_new_file_creation(self, action: FileEditAction) -> Observation:
        """Handle file edit when file doesn't exist - create new file."""
        obs = self.write(
            FileWriteAction(path=action.path, content=action.content.strip())
        )
        if isinstance(obs, ErrorObservation):
            return obs
        if not isinstance(obs, FileWriteObservation):
            msg = f"Expected FileWriteObservation, got {type(obs)}: {obs!s}"
            raise ValueError(msg)
        return FileEditObservation(
            content=get_diff("", action.content, action.path),
            path=action.path,
            prev_exist=False,
            old_content="",
            new_content=action.content,
        )

    def _handle_append_edit(
        self,
        action: FileEditAction,
        original_content: str,
        old_lines: list[str],
        retry_num: int,
    ) -> Observation:
        """Handle appending content to end of file (start == -1)."""
        updated_content = "\n".join(old_lines + action.content.split("\n"))
        diff = get_diff(original_content, updated_content, action.path)

        if self.config.runtime_config.enable_auto_lint:
            suffix = os.path.splitext(action.path)[1]
            error_obs = self._get_lint_error(
                suffix, original_content, updated_content, action.path, diff
            )
            if error_obs is not None:
                self.write(FileWriteAction(path=action.path, content=updated_content))
                return self.correct_edit(
                    file_content=updated_content,
                    error_obs=error_obs,
                    retry_num=retry_num,
                )

        self.write(FileWriteAction(path=action.path, content=updated_content))
        return FileEditObservation(
            content=diff,
            path=action.path,
            prev_exist=True,
            old_content=original_content,
            new_content=updated_content,
        )

    def _build_range_error_message(
        self,
        action: FileEditAction,
        start_idx: int,
        end_idx: int,
        length_of_range: int,
        original_content: str,
    ) -> str:
        """Build error message with relevant snippets when edit range is too long."""
        error_msg = f"[Edit error: The range of lines to edit is too long.]\n[The maximum number of lines allowed to edit at once is {
            MAX_LINES_TO_EDIT
        }. Got (L{start_idx + 1}-L{end_idx}) {length_of_range} lines.]\n"

        topk_chunks: list[Chunk] = get_top_k_chunk_matches(
            text=original_content,
            query=action.content,
            k=3,
            max_chunk_size=20,
        )
        error_msg += (
            "Here are some snippets that maybe relevant to the provided edit.\n"
        )

        for i, chunk in enumerate(topk_chunks):
            line_mid = (chunk.line_range[0] + chunk.line_range[1]) // 2
            error_msg += f"[begin relevant snippet {i + 1}. Line range: L{
                chunk.line_range[0]
            }-L{chunk.line_range[1]}. Similarity: {chunk.normalized_lcs}]\n"
            error_msg += (
                f'[Browse around it via `open_file("{action.path}", {line_mid})`]\n'
            )
            error_msg += chunk.visualize() + "\n"
            error_msg += f"[end relevant snippet {i + 1}]\n"
            error_msg += "-" * 40 + "\n"

        error_msg += "Consider using `open_file` to explore around the relevant snippets if needed.\n"
        error_msg += f'**IMPORTANT**: Please REDUCE the range of edits to less than {
            MAX_LINES_TO_EDIT
        } lines by setting `start` and `end` in the edit action (e.g. `<file_edit path="{
            action.path
        }" start=[PUT LINE NUMBER HERE] end=[PUT LINE NUMBER HERE] />`). '
        return error_msg

    def _perform_llm_edit(
        self,
        action: FileEditAction,
        original_content: str,
        old_lines: list[str],
        start_idx: int,
        end_idx: int,
        retry_num: int,
    ) -> Observation:
        """Perform the actual LLM-based edit on the specified range."""
        content_to_edit = "\n".join(old_lines[start_idx:end_idx])
        draft_llm = self._require_draft_editor_llm()
        _edited_content = get_new_file_contents(
            draft_llm, content_to_edit, action.content
        )

        if _edited_content is None:
            ret_err = ErrorObservation(
                "Failed to get new file contents. Please try to reduce the number of edits and try again.",
            )
            ret_err.llm_metrics = draft_llm.metrics
            return ret_err

        updated_lines = (
            old_lines[:start_idx] + _edited_content.split("\n") + old_lines[end_idx:]
        )
        updated_content = "\n".join(updated_lines)
        diff = get_diff(original_content, updated_content, action.path)

        if self.config.runtime_config.enable_auto_lint:
            suffix = os.path.splitext(action.path)[1]
            error_obs = self._get_lint_error(
                suffix, original_content, updated_content, action.path, diff
            )
            if error_obs is not None:
                error_obs.llm_metrics = draft_llm.metrics
                self.write(FileWriteAction(path=action.path, content=updated_content))
                return self.correct_edit(
                    file_content=updated_content,
                    error_obs=error_obs,
                    retry_num=retry_num,
                )

        self.write(FileWriteAction(path=action.path, content=updated_content))
        ret_obs = FileEditObservation(
            content=diff,
            path=action.path,
            prev_exist=True,
            old_content=original_content,
            new_content=updated_content,
        )
        ret_obs.llm_metrics = draft_llm.metrics
        return ret_obs

    def llm_based_edit(self, action: FileEditAction, retry_num: int = 0) -> Observation:
        """Perform LLM-based file editing with automatic linting and correction.

        Args:
            action: File edit action specifying path, range, and content
            retry_num: Current retry attempt for correction (default 0)

        Returns:
            FileEditObservation on success, ErrorObservation on failure

        """
        # Read the file and handle non-existent case
        prep_result = self._prepare_edit_content(action)
        if isinstance(prep_result, Observation):
            return prep_result

        original_file_content, old_file_lines = prep_result

        # Validate range
        error = self._validate_range(action.start, action.end, len(old_file_lines))
        if error is not None:
            return error

        # Handle append mode (start == -1)
        if action.start == -1:
            return self._handle_append_edit(
                action, original_file_content, old_file_lines, retry_num
            )

        # Calculate and check edit range
        start_idx, end_idx, length_of_range = self._calculate_edit_range(
            action, old_file_lines
        )

        # Check if range is too long
        if length_of_range > MAX_LINES_TO_EDIT + 1:
            error_msg = self._build_range_error_message(
                action,
                start_idx,
                end_idx,
                length_of_range,
                original_file_content,
            )
            return ErrorObservation(error_msg)

        # Perform the edit
        return self._perform_llm_edit(
            action, original_file_content, old_file_lines, start_idx, end_idx, retry_num
        )

    def _prepare_edit_content(
        self, action: FileEditAction
    ) -> tuple[str, list[str]] | Observation:
        """Read file and prepare content lines. Returns Observation on error/creation."""
        obs = self.read(FileReadAction(path=action.path))

        if (
            isinstance(obs, ErrorObservation)
            and "File not found".lower() in obs.content.lower()
        ):
            logger.debug(
                "Agent attempted to edit a file that does not exist. Creating the file. Error msg: %s",
                obs.content,
            )
            return self._handle_new_file_creation(action)

        if not isinstance(obs, FileReadObservation):
            if isinstance(obs, ErrorObservation):
                return obs
            msg = f"Expected FileReadObservation, got {type(obs)}: {obs!s}"
            raise ValueError(msg)

        content = obs.content
        lines = content.split("\n")
        return content, lines

    def _calculate_edit_range(
        self, action: FileEditAction, old_file_lines: list[str]
    ) -> tuple[int, int, int]:
        """Calculate start_idx, end_idx and length_of_range."""
        start_idx = action.start - 1
        if action.end != -1:
            end_idx = action.end - 1 + 1
        else:
            end_idx = len(old_file_lines)
        length_of_range = end_idx - start_idx
        return start_idx, end_idx, length_of_range

    def check_retry_num(self, retry_num):
        """Check if retry limit exceeded for LLM-based correction.

        Args:
            retry_num: Current retry number

        Returns:
            True if retry limit exceeded

        """
        draft_llm = self._require_draft_editor_llm()
        correct_num = draft_llm.config.correct_num
        return correct_num < retry_num

    def correct_edit(
        self, file_content: str, error_obs: ErrorObservation, retry_num: int = 0
    ) -> Observation:
        """Attempt to automatically correct a failed edit using LLM.

        Args:
            file_content: Current file content after failed edit
            error_obs: Error observation from failed edit
            retry_num: Current retry attempt

        Returns:
            Corrected observation or original error if correction fails

        """
        import backend.engine.function_calling as orchestrator_function_calling
        from backend.engine.tools import create_llm_based_edit_tool
        from backend.inference.llm_utils import check_tools

        _retry_num = retry_num + 1
        if self.check_retry_num(_retry_num):
            return error_obs
        draft_llm = self._require_draft_editor_llm()
        tools = check_tools([dict(create_llm_based_edit_tool())], draft_llm.config)
        messages = [
            {"role": "system", "content": CORRECT_SYS_MSG},
            {
                "role": "user",
                "content": CORRECT_USER_MSG.format(
                    file_content=file_content, lint_error=error_obs.content
                ),
            },
        ]
        params: dict = {"messages": messages, "tools": tools}
        try:
            response = draft_llm.completion(**params)
            actions = orchestrator_function_calling.response_to_actions(response)
            if len(actions) != 1:
                return error_obs
            for action in actions:
                if isinstance(action, FileEditAction):
                    return self.llm_based_edit(action, _retry_num)
        except Exception as e:
            logger.error("correct lint error is failed: %s", e)
        return error_obs
