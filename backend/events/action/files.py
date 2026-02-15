"""File manipulation action types used by Forge agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from backend.core.enums import ActionSecurityRisk, FileEditSource, FileReadSource
from backend.core.schemas import ActionType
from backend.events.action.action import Action


@dataclass
class FileReadAction(Action):
    """Reads a file from a given path.

    Can be set to read specific lines using start and end
    Default lines 0:-1 (whole file).
    """

    path: str = ""
    start: int = 0
    end: int = -1
    thought: str = ""
    action: ClassVar[str] = ActionType.READ
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN
    impl_source: FileReadSource = FileReadSource.DEFAULT
    view_range: list[int] | None = None

    @property
    def message(self) -> str:
        """Get file read message."""
        return f"Reading file: {self.path}"

    __test__ = False


@dataclass
class FileWriteAction(Action):
    """Writes a file to a given path.

    Can be set to write specific lines using start and end
    Default lines 0:-1 (whole file).
    """

    path: str = ""
    content: str = ""
    start: int = 0
    end: int = -1
    thought: str = ""
    action: ClassVar[str] = ActionType.WRITE
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get file write message."""
        return f"Writing file: {self.path}"

    def __repr__(self) -> str:
        """Return a readable summary of the write parameters."""
        return f"**FileWriteAction**\nPath: {self.path}\nRange: [L{self.start}:L{
            self.end
        }]\nThought: {self.thought}\nContent:\n```\n{self.content}\n```\n"

    __test__ = False


@dataclass
class FileEditAction(Action):
    """Edits a file using various commands including view, create, str_replace, insert, and undo_edit.

    This class supports two main modes of operation:
    1. LLM-based editing (impl_source = FileEditSource.LLM_BASED_EDIT)
    2. File editor-based editing (impl_source = FileEditSource.FILE_EDITOR)

    Attributes:
        path (str): The path to the file being edited. Works for both LLM-based and FILE_EDITOR editing.
        FILE_EDITOR only arguments:
            command (str): The editing command to be performed (view, create, str_replace, insert, undo_edit, write).
            file_text (str): The content of the file to be created (used with 'create' command in FILE_EDITOR mode).
            old_str (str): The string to be replaced (used with 'str_replace' command in FILE_EDITOR mode).
            new_str (str): The string to replace old_str (used with 'str_replace' and 'insert' commands in FILE_EDITOR mode).
            insert_line (int): The line number after which to insert new_str (used with 'insert' command in FILE_EDITOR mode).
        LLM-based editing arguments:
            content (str): The content to be written or edited in the file (used in LLM-based editing and 'write' command).
            start (int): The starting line for editing (1-indexed, inclusive). Default is 1.
            end (int): The ending line for editing (1-indexed, inclusive). Default is -1 (end of file).
            thought (str): The reasoning behind the edit action.
            action (str): The type of action being performed (always ActionType.EDIT).
        runnable (bool): Indicates if the action can be executed (always True).
        security_risk (ActionSecurityRisk | None): Indicates any security risks associated with the action.
        impl_source (FileEditSource): The source of the implementation (LLM_BASED_EDIT or FILE_EDITOR).

    Usage:
        - For LLM-based editing: Use path, content, start, and end attributes.
        - For FILE_EDITOR-based editing: Use path, command, and the appropriate attributes for the specific command.

    Note:
        - If start is set to -1 in LLM-based editing, the content will be appended to the file.
        - The 'write' command behaves similarly to LLM-based editing, using content, start, and end attributes.

    """

    path: str = ""
    command: str = ""
    file_text: str | None = None
    old_str: str | None = None
    new_str: str | None = None
    insert_line: int | None = None
    content: str = ""
    start: int = 1
    end: int = -1
    thought: str = ""
    action: ClassVar[str] = ActionType.EDIT
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN
    impl_source: FileEditSource = FileEditSource.FILE_EDITOR

    def __repr__(self) -> str:
        """Return a readable summary capturing edit mode and key fields."""
        ret = "**FileEditAction**\n"
        ret += f"Path: [{self.path}]\n"
        ret += f"Thought: {self.thought}\n"
        if self.impl_source == FileEditSource.LLM_BASED_EDIT:
            ret += f"Range: [L{self.start}:L{self.end}]\n"
            ret += f"Content:\n```\n{self.content}\n```\n"
        else:
            ret += f"Command: {self.command}\n"
            if self.command == "create":
                ret += f"Created File with Text:\n```\n{self.file_text}\n```\n"
            elif self.command == "str_replace":
                ret += f"Old String: ```\n{self.old_str}\n```\n"
                ret += f"New String: ```\n{self.new_str}\n```\n"
            elif self.command == "insert":
                ret += f"Insert Line: {self.insert_line}\n"
                ret += f"New String: ```\n{self.new_str}\n```\n"
            elif self.command == "undo_edit":
                ret += "Undo Edit\n"
        return ret

    __test__ = False
