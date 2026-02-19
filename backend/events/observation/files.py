"""File-related observation classes for tracking file operations."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import ClassVar

from backend.core.schemas import ObservationType
from backend.core.enums import FileEditSource, FileReadSource
from backend.events.observation.observation import Observation


@dataclass
class FileReadObservation(Observation):
    """This data class represents the content of a file."""

    path: str
    impl_source: FileReadSource = FileReadSource.DEFAULT
    observation: ClassVar[str] = ObservationType.READ

    @property
    def message(self) -> str:
        """Get a human-readable message describing the file read operation."""
        return f"I read the file {self.path}."

    def __str__(self) -> str:
        """Get a string representation of the file read observation."""
        return f"[Read from {self.path} is successful.]\n{self.content}"

    __test__ = False


@dataclass
class FileWriteObservation(Observation):
    """This data class represents a file write operation."""

    path: str
    observation: ClassVar[str] = ObservationType.WRITE

    @property
    def message(self) -> str:
        """Get a human-readable message describing the file write operation."""
        return f"I wrote to the file {self.path}."

    def __str__(self) -> str:
        """Get a string representation of the file write observation."""
        return f"[Write to {self.path} is successful.]\n{self.content}"

    __test__ = False


@dataclass
class FileEditObservation(Observation):
    """This data class represents a file edit operation.

    The observation includes both the old and new content of the file, and can
    generate a diff visualization showing the changes. The diff is computed lazily
    and cached to improve performance.

    The .content property can either be:
      - Git diff in LLM-based editing mode
      - the rendered message sent to the LLM in FILE_EDITOR mode (e.g., "The file /path/to/file.txt is created with the provided content.")
    """

    path: str = ""
    prev_exist: bool = False
    old_content: str | None = None
    new_content: str | None = None
    impl_source: FileEditSource = FileEditSource.LLM_BASED_EDIT
    diff: str | None = None
    preview: bool = False
    _diff_cache: str | None = None
    observation: ClassVar[str] = ObservationType.EDIT

    @property
    def message(self) -> str:
        """Get a human-readable message describing the file edit operation."""
        return f"I edited the file {self.path}."

    def _calculate_indent_pad_size(self, group: list) -> int:
        """Calculate the padding size for line numbers."""
        return len(str(group[-1][3])) + 1

    def _add_equal_lines(
        self,
        cur_group: dict,
        old_lines: list,
        new_lines: list,
        i1: int,
        i2: int,
        j1: int,
        j2: int,
        indent_pad_size: int,
    ) -> None:
        """Add equal lines to both before and after edits."""
        for idx, line in enumerate(old_lines[i1:i2]):
            line_num = i1 + idx + 1
            cur_group["before_edits"].append(f"{line_num:>{indent_pad_size}}|{line}")
        for idx, line in enumerate(new_lines[j1:j2]):
            line_num = j1 + idx + 1
            cur_group["after_edits"].append(f"{line_num:>{indent_pad_size}}|{line}")

    def _add_deleted_lines(
        self, cur_group: dict, old_lines: list, i1: int, i2: int, indent_pad_size: int
    ) -> None:
        """Add deleted lines to before_edits."""
        for idx, line in enumerate(old_lines[i1:i2]):
            line_num = i1 + idx + 1
            cur_group["before_edits"].append(
                f"-{line_num:>{indent_pad_size - 1}}|{line}"
            )

    def _add_inserted_lines(
        self, cur_group: dict, new_lines: list, j1: int, j2: int, indent_pad_size: int
    ) -> None:
        """Add inserted lines to after_edits."""
        for idx, line in enumerate(new_lines[j1:j2]):
            line_num = j1 + idx + 1
            cur_group["after_edits"].append(
                f"+{line_num:>{indent_pad_size - 1}}|{line}"
            )

    def _process_opcode_group(
        self, group: list, old_lines: list, new_lines: list
    ) -> dict[str, list[str]]:
        """Process a single opcode group and return the edit group."""
        indent_pad_size = self._calculate_indent_pad_size(group)
        cur_group: dict[str, list[str]] = {"before_edits": [], "after_edits": []}

        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                self._add_equal_lines(
                    cur_group, old_lines, new_lines, i1, i2, j1, j2, indent_pad_size
                )
            elif tag in {"replace", "delete"}:
                self._add_deleted_lines(cur_group, old_lines, i1, i2, indent_pad_size)
            if tag in {"replace", "insert"}:
                self._add_inserted_lines(cur_group, new_lines, j1, j2, indent_pad_size)

        return cur_group

    def get_edit_groups(self, n_context_lines: int = 2) -> list[dict[str, list[str]]]:
        """Get the edit groups showing changes between old and new content.

        Args:
            n_context_lines: Number of context lines to show around each change.

        Returns:
            A list of edit groups, where each group contains before/after edits.

        """
        if self.old_content is None or self.new_content is None:
            return []

        old_lines = self.old_content.split("\n")
        new_lines = self.new_content.split("\n")
        edit_groups: list[dict] = []

        for group in SequenceMatcher(None, old_lines, new_lines).get_grouped_opcodes(
            n_context_lines
        ):
            cur_group = self._process_opcode_group(group, old_lines, new_lines)
            edit_groups.append(cur_group)

        return edit_groups

    def visualize_diff(
        self, n_context_lines: int = 2, change_applied: bool = True
    ) -> str:
        """Visualize the diff of the file edit. Used in the LLM-based editing mode.

        Instead of showing the diff line by line, this function shows each hunk
        of changes as a separate entity.

        Args:
            n_context_lines: Number of context lines to show before/after changes.
            change_applied: Whether changes are applied. If false, shows as
                attempted edit.

        Returns:
            A string containing the formatted diff visualization.

        """
        if self._diff_cache is not None:
            return self._diff_cache
        if change_applied and self.old_content == self.new_content:
            msg = (
                "(no changes detected. Please make sure your edits change "
                "the content of the existing file.)\n"
            )
            self._diff_cache = msg
            return self._diff_cache
        edit_groups = self.get_edit_groups(n_context_lines=n_context_lines)
        if change_applied:
            header = f"[Existing file {self.path} is edited with "
            header += f"{len(edit_groups)} changes.]"
        else:
            header = f"[Changes are NOT applied to {self.path} - Here's how "
            header += "the file looks like if changes are applied.]"
        result = [header]
        op_type = "edit" if change_applied else "ATTEMPTED edit"
        for i, cur_edit_group in enumerate(edit_groups):
            if i != 0:
                result.append("-------------------------")
            result.extend(
                (
                    f"[begin of {op_type} {i + 1} / {len(edit_groups)}]",
                    f"(content before {op_type})",
                )
            )
            result.extend(cur_edit_group["before_edits"])
            result.append(f"(content after {op_type})")
            result.extend(cur_edit_group["after_edits"])
            result.append(f"[end of {op_type} {i + 1} / {len(edit_groups)}]")
        self._diff_cache = "\n".join(result)
        return self._diff_cache

    def __str__(self) -> str:
        """Get a string representation of the file edit observation."""
        if self.impl_source == FileEditSource.FILE_EDITOR:
            return self.content
        if not self.prev_exist:
            assert self.old_content == "", (
                "old_content should be empty if the file is new (prev_exist=False)."
            )
            return f"[New file {self.path} is created with the provided content.]\n"
        return self.visualize_diff().rstrip() + "\n"

    __test__ = False
