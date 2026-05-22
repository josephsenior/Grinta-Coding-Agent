"""File manipulation action types used by Grinta agents."""

from __future__ import annotations

from dataclasses import dataclass, field
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
class StartFileEditAction(Action):
    """Starts a two-mode file-edit transaction without carrying file content."""

    path: str = ''
    operation: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    transaction_id: str | None = None
    delimiter: str | None = None
    thought: str = ''
    action: ClassVar[str] = ActionType.START_FILE_EDIT
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN

    @property
    def message(self) -> str:
        return f'Starting file edit: {self.operation} {self.path}'


@dataclass
class FileEditAction(Action):
    """Edits a file using canonical file-editor commands.

    Attributes:
        path (str): The path to the file being edited.
        command (str): The editing command to be performed (read_file, create_file, insert_text, undo_last_edit, edit).
        file_text (str): The content of the file to be created (used with 'create_file').
        new_str (str): The replacement text (used with 'insert_text' or range edits).
        insert_line (int): The line number after which to insert new_str (used with 'insert_text').
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
    new_str: str | None = None
    insert_line: int | None = None
    view_range: list[int] | None = None
    thought: str = ''
    action: ClassVar[str] = ActionType.EDIT
    runnable: ClassVar[bool] = True
    security_risk: ActionSecurityRisk = ActionSecurityRisk.UNKNOWN
    impl_source: FileEditSource = FileEditSource.FILE_EDITOR
    edit_mode: str | None = None
    expected_hash: str | None = None
    expected_file_hash: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    overwrite_existing: bool = False

    def __repr__(self) -> str:
        """Return a readable summary capturing edit mode and key fields."""
        ret = '**FileEditAction**\n'
        ret += f'Path: [{self.path}]\n'
        ret += f'Thought: {self.thought}\n'
        ret += f'Command: {self.command}\n'
        if self.command == 'create_file':
            ret += f'Created File with Text:\n```\n{self.file_text}\n```\n'
        elif self.command == 'insert_text':
            ret += f'Insert Line: {self.insert_line}\n'
            ret += f'New String: ```\n{self.new_str}\n```\n'
        elif self.command == 'edit' and self.edit_mode == 'range':
            ret += f'Range: [L{self.start_line}:L{self.end_line}]\n'
            ret += f'New String: ```\n{self.new_str}\n```\n'
        elif self.command == 'undo_last_edit':
            ret += 'Undo Edit\n'
        return ret
