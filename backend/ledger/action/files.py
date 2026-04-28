"""File manipulation action types used by App agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from backend.core.enums import ActionSecurityRisk, FileEditSource, FileReadSource
from backend.core.schemas import ActionType
from backend.ledger.action.action import Action


@dataclass
class FileReadAction(Action):
    """Reads a file from a given path.

    Can be set to read specific lines using start and end
    Default lines 0:-1 (whole file).
    """

    path: str = ''
    start: int = 0
    end: int = -1
    thought: str = ''
    action: ClassVar[str] = ActionType.READ
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN
    impl_source: FileReadSource = FileReadSource.DEFAULT
    view_range: list[int] | None = None

    @property
    def message(self) -> str:
        """Get file read message."""
        return f'Reading file: {self.path}'


@dataclass
class FileWriteAction(Action):
    """Writes a file to a given path.

    Can be set to write specific lines using start and end
    Default lines 0:-1 (whole file).
    """

    path: str = ''
    content: str = ''
    start: int = 0
    end: int = -1
    thought: str = ''
    action: ClassVar[str] = ActionType.WRITE
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        """Get file write message."""
        return f'Writing file: {self.path}'

    def __repr__(self) -> str:
        """Return a readable summary of the write parameters."""
        range_str = f'[L{self.start}:L{self.end}]'
        return (
            f'**FileWriteAction**\nPath: {self.path}\nRange: {range_str}'
            f'\nThought: {self.thought}\nContent:\n```\n{self.content}\n```\n'
        )


@dataclass
class FileEditAction(Action):
    """Edits a file using canonical file-editor commands.

    Attributes:
        path (str): The path to the file being edited.
        command (str): The editing command to be performed (read_file, create_file, replace_text [internal substring replace], insert_text, undo_last_edit, write).
        file_text (str): The content of the file to be created (used with 'create_file').
        old_str (str): The string to be replaced (substring replace).
        new_str (str): The replacement text (substring replace and insert_text).
        insert_line (int): The line number after which to insert new_str (used with 'insert_text').
        content (str): Optional raw content payload kept for legacy compatibility.
        start (int): Optional starting line for legacy payloads. Default is 1.
        end (int): Optional ending line for legacy payloads. Default is -1 (end of file).
        thought (str): The reasoning behind the edit action.
        action (str): The type of action being performed (always ActionType.EDIT).
        runnable (bool): Indicates if the action can be executed (always True).
        security_risk (ActionSecurityRisk | None): Indicates any security risks associated with the action.
        impl_source (FileEditSource): The source of the implementation.

    Usage:
        - Use path, command, and the appropriate attributes for the specific command.

    """

    path: str = ''
    command: str = ''
    file_text: str | None = None
    old_str: str | None = None
    new_str: str | None = None
    normalize_ws: bool | None = None
    insert_line: int | None = None
    view_range: list[int] | None = None
    content: str = ''
    start: int = 1
    end: int = -1
    thought: str = ''
    action: ClassVar[str] = ActionType.EDIT
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN
    impl_source: FileEditSource = FileEditSource.FILE_EDITOR
    # text_editor / FileEditor extended options (optional)
    edit_mode: str | None = None
    format_kind: str | None = None
    format_op: str | None = None
    format_path: str | None = None
    format_value: Any = None
    anchor_type: str | None = None
    anchor_value: str | None = None
    anchor_occurrence: int | None = None
    section_action: str | None = None
    section_content: str | None = None
    patch_text: str | None = None
    expected_hash: str | None = None
    expected_file_hash: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    def __repr__(self) -> str:
        """Return a readable summary capturing edit mode and key fields."""
        ret = '**FileEditAction**\n'
        ret += f'Path: [{self.path}]\n'
        ret += f'Thought: {self.thought}\n'
        if not self.command and self.content:
            ret += f'Range: [L{self.start}:L{self.end}]\n'
            ret += f'Content:\n```\n{self.content}\n```\n'
        else:
            ret += f'Command: {self.command}\n'
            if self.command == 'create_file':
                ret += f'Created File with Text:\n```\n{self.file_text}\n```\n'
            elif self.command == 'replace_text':
                ret += f'Old String: ```\n{self.old_str}\n```\n'
                ret += f'New String: ```\n{self.new_str}\n```\n'
                if self.normalize_ws is not None:
                    ret += f'Normalize WS: {self.normalize_ws}\n'
            elif self.command == 'insert_text':
                ret += f'Insert Line: {self.insert_line}\n'
                ret += f'New String: ```\n{self.new_str}\n```\n'
            elif self.command == 'undo_last_edit':
                ret += 'Undo Edit\n'
        return ret
