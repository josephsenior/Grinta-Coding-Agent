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
    MAX_CMD_OUTPUT_SIZE,
)
from backend.core.logger import app_logger as logger
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
                'py_interpreter_path': '$(which python 2>/dev/null || echo "")',
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
        """Initialize the observation, coercing metadata and truncating content if needed."""
        truncate = not hidden
        if truncate:
            content = self._maybe_truncate(content)
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

    _ERROR_LINE_PATTERNS = re.compile(
        r'(?i)\b(error|warning|FAILED|FAIL|traceback|exception|panic'
        r'|ModuleNotFoundError|ImportError|SyntaxError|TypeError|ValueError'
        r'|NameError|AttributeError|KeyError|IndexError|FileNotFoundError'
        r'|PermissionError|RuntimeError|AssertionError|OSError|IOError'
        r'|ENOENT|EACCES|EPERM|segfault|Segmentation fault'
        r'|npm ERR|cargo error|compile error|build failed)\b',
    )

    @classmethod
    def _maybe_truncate(cls, content: str, max_size: int = MAX_CMD_OUTPUT_SIZE) -> str:
        """Truncate content while preserving error-relevant lines from the middle.

        Strategy:
        - Keep first ~15% of content (command echo + initial output)
        - Keep last ~35% of content (final errors + exit info)
        - From the middle ~50%, keep only lines matching error patterns with 2 lines of context
        - This preserves critical diagnostic info that blind head+tail truncation would lose

        Args:
            content: The content to truncate
            max_size: Maximum size before truncation. Defaults to MAX_CMD_OUTPUT_SIZE.

        Returns:
            Original content if not too large, or smart-truncated content otherwise

        """
        if len(content) <= max_size:
            return content

        head_budget = max_size * 15 // 100
        tail_budget = max_size * 35 // 100
        middle_budget = max_size - head_budget - tail_budget
        head = content[:head_budget]
        tail = content[-tail_budget:]
        middle = (
            content[head_budget:-tail_budget]
            if tail_budget > 0
            else content[head_budget:]
        )
        middle_lines = middle.splitlines(keepends=True)

        error_line_indices = cls._find_error_line_indices(middle_lines)
        middle_preserved = cls._build_middle_preserved(
            middle_lines, error_line_indices, middle_budget
        )

        truncated = cls._build_truncated_output(
            head, tail, middle_preserved, len(content), error_line_indices
        )
        logger.debug(
            'Smart-truncated command output: %s -> %s chars (%d error lines kept)',
            len(content),
            len(truncated),
            len(error_line_indices),
        )
        return truncated

    @classmethod
    def _find_error_line_indices(cls, middle_lines: list[str]) -> set[int]:
        """Find indices of lines matching error patterns, plus 2-line context."""
        indices: set[int] = set()
        for i, line in enumerate(middle_lines):
            if cls._ERROR_LINE_PATTERNS.search(line):
                for ctx in range(max(0, i - 2), min(len(middle_lines), i + 3)):
                    indices.add(ctx)
        return indices

    @classmethod
    def _build_middle_preserved(
        cls, middle_lines: list[str], error_indices: set[int], middle_budget: int
    ) -> str:
        """Build preserved middle section from error-relevant lines within budget."""
        if not error_indices:
            return ''
        kept: list[str] = []
        prev_idx = -2
        current_size = 0
        for idx in sorted(error_indices):
            if current_size >= middle_budget:
                break
            if idx > prev_idx + 1:
                kept.append('  [...]\n')
                current_size += 8
            kept.append(middle_lines[idx])
            current_size += len(middle_lines[idx])
            prev_idx = idx
        return ''.join(kept)

    @classmethod
    def _build_truncated_output(
        cls,
        head: str,
        tail: str,
        middle_preserved: str,
        original_length: int,
        error_indices: set[int],
    ) -> str:
        """Assemble truncated output with markers."""
        retained = len(head) + len(middle_preserved) + len(tail)
        pct = round(retained / original_length * 100) if original_length else 100
        marker = (
            f'\n[... Observation truncated: {original_length} chars → ~{retained} chars '
            f'({pct}% retained, {len(error_indices)} error-relevant lines preserved from middle) ...]\n'
        )
        return head + marker + middle_preserved + marker + tail

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
        return ret
