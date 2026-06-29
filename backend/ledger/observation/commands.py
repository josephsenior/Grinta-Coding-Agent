"""Observations produced by command execution."""

from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass, field
from typing import Any, ClassVar, Self

from backend.core.constants import (
    CMD_OUTPUT_PS1_BEGIN,
    CMD_OUTPUT_PS1_END,
)
from backend.core.logging.logger import app_logger as logger
from backend.core.schemas import ObservationType
from backend.core.schemas.metadata import CmdOutputMetadataSchema
from backend.ledger.observation.observation import Observation

CMD_OUTPUT_METADATA_PS1_REGEX = re.compile(
    f'^{CMD_OUTPUT_PS1_BEGIN.strip()}(.*?){CMD_OUTPUT_PS1_END.strip()}',
    re.DOTALL | re.MULTILINE,
)


class CmdOutputMetadata(CmdOutputMetadataSchema):
    """Additional metadata captured from PS1."""

    @classmethod
    def to_ps1_prompt(cls) -> str:
        """Convert the required metadata into a PS1 prompt."""
        prompt = CMD_OUTPUT_PS1_BEGIN
        json_str = json.dumps(
            {
                'pid': '$!',
                'exit_code': '$?',
                'username': '\\u',
                'hostname': '\\h',
                'working_dir': '$(pwd)',
                'py_interpreter_path': (
                    '$(command -v python3 2>/dev/null '
                    '|| command -v python 2>/dev/null '
                    '|| command -v py 2>/dev/null '
                    '|| echo "")'
                ),
            },
            indent=2,
        )
        prompt += json_str.replace('"', '\\"')
        prompt += CMD_OUTPUT_PS1_END + '\n'
        return prompt

    @classmethod
    def matches_ps1_metadata(cls, string: str) -> list[re.Match[str]]:
        """Find all PS1 metadata blocks in command output.

        Args:
            string: Command output string to search

        Returns:
            List of regex matches for PS1 metadata blocks

        """
        matches = []
        for match in CMD_OUTPUT_METADATA_PS1_REGEX.finditer(string):
            try:
                json.loads(match.group(1).strip())
                matches.append(match)
            except json.JSONDecodeError:
                logger.warning(
                    'Failed to parse PS1 metadata: %s. Skipping.%s',
                    match.group(1),
                    traceback.format_exc(),
                )
                continue
        return matches

    @classmethod
    def from_ps1_match(cls, match: re.Match[str]) -> Self:
        """Extract the required metadata from a PS1 prompt."""
        metadata = json.loads(match.group(1))
        processed = metadata.copy()
        if 'pid' in metadata:
            try:
                processed['pid'] = int(float(str(metadata['pid'])))
            except (ValueError, TypeError):
                processed['pid'] = -1
        if 'exit_code' in metadata:
            try:
                processed['exit_code'] = int(float(str(metadata['exit_code'])))
            except (ValueError, TypeError):
                logger.warning(
                    'Failed to parse exit code: %s. Setting to -1.',
                    metadata['exit_code'],
                )
                processed['exit_code'] = -1
        return cls(**processed)


@dataclass
class CmdOutputObservation(Observation):
    """This data class represents the output of a command."""

    command: str
    metadata: CmdOutputMetadata = field(default_factory=CmdOutputMetadata)
    hidden: bool = False
    observation_type: ClassVar[str] = ObservationType.RUN

    def __init__(
        self,
        content: str,
        command: str,
        observation: str = ObservationType.RUN,
        metadata: dict[str, Any] | CmdOutputMetadata | None = None,
        hidden: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize the observation, coercing metadata.

        Note: content truncation is intentionally NOT done here. The
        execution layer (``truncate_cmd_output`` in
        ``backend.execution.aes.file_operations``) is the primary
        truncator for shell output — it is env-configurable via
        ``APP_MAX_CMD_OUTPUT_CHARS`` (default 40 000) and uses an
        error-aware head/tail strategy with test-summary extraction.
        The observation processor layer (``truncate_content``) is the
        final safety net for ALL observation types (browser, shell, etc.).
        Doing truncation in ``__init__`` pre-empted the execution-layer
        truncator at a hardcoded 10 000 chars, making the env var
        ineffective and the sophisticated strategy dead code.
        """
        super().__init__(content)
        self.command = command
        # Store observation value in a private attribute to avoid ClassVar conflict
        object.__setattr__(self, 'observation', observation)
        self.hidden = hidden
        if isinstance(metadata, dict):
            self.metadata = CmdOutputMetadata(**metadata)
        else:
            self.metadata = metadata or CmdOutputMetadata()
        if 'exit_code' in kwargs:
            self.metadata.exit_code = kwargs['exit_code']
        if 'command_id' in kwargs:
            self.metadata.pid = kwargs['command_id']

        # Synchronize with base Observation exit_code
        self.exit_code = self.metadata.exit_code

    @property
    def command_id(self) -> int:
        """Get command process ID."""
        return self.metadata.pid

    @command_id.setter
    def command_id(self, value: int) -> None:
        """Set command process ID."""
        self.metadata.pid = value

    @property
    def exit_code(self) -> int:
        """Get command exit code."""
        return self.metadata.exit_code

    @exit_code.setter
    def exit_code(self, value: int) -> None:
        """Set command exit code."""
        self.metadata.exit_code = value

    @property
    def error(self) -> bool:
        """Check if command failed (non-zero exit code)."""
        return self.exit_code != 0

    @property
    def message(self) -> str:
        """Get formatted command completion message."""
        return f'Command `{self.command}` executed with exit code {self.exit_code}.'

    @property
    def success(self) -> bool:
        """Check if command succeeded (zero exit code)."""
        return not self.error

    def __str__(self) -> str:
        """Return a readable summary including metadata and agent-facing text."""
        from backend.core.pydantic_compat import model_dump_with_options

        try:
            metadata_json = json.dumps(model_dump_with_options(self.metadata), indent=2)
        except Exception:
            metadata_json = repr(self.metadata)
        return f'**CmdOutputObservation (source={self.source}, exit code={
            self.exit_code
        }, metadata={metadata_json})**\n--BEGIN AGENT OBSERVATION--\n{
            self.to_agent_observation()
        }\n--END AGENT OBSERVATION--'

    def to_agent_observation(self) -> str:
        """Format observation for agent with metadata context.

        Returns:
            Formatted observation string with working directory and exit code info

        """
        ret = f'{self.metadata.prefix}{self.content}{self.metadata.suffix}'
        if self.metadata.working_dir:
            ret += f'\n[Current working directory: {self.metadata.working_dir}]'
        if self.metadata.py_interpreter_path:
            ret += f'\n[Python interpreter: {self.metadata.py_interpreter_path}]'
        if self.metadata.exit_code != -1:
            ret += f'\n[Command finished with exit code {self.metadata.exit_code}]'
        if self.metadata.timeout_kind:
            ret += (
                '\n[timeout_kind='
                f'{self.metadata.timeout_kind} '
                f'partial_output={self.metadata.partial_output} '
                f'command_still_running={self.metadata.command_still_running}]'
            )
        return ret
