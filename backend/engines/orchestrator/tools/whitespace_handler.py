"""Whitespace intelligence utilities for universal indentation handling.

Handles indentation normalization and auto-correction for all languages.
Never breaks code due to tabs versus spaces or indentation mismatches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from backend.core.constants import DEFAULT_INDENT_SIZES


class IndentStyle(Enum):
    """Indentation style."""

    SPACES = "spaces"
    TABS = "tabs"
    MIXED = "mixed"


@dataclass
class IndentConfig:
    """Indentation configuration for a file."""

    style: IndentStyle
    size: int  # Number of spaces per level (or 1 for tabs)
    line_ending: str  # \n or \r\n


class WhitespaceHandler:
    """Universal whitespace and indentation handler.

    Features:
    - Detects existing indentation style (tabs vs. spaces)
    - Normalizes inconsistent whitespace
    - Auto-indents new code blocks
    - Preserves intentional blank lines
    - Handles ALL languages
    """

    @staticmethod
    def _detect_line_ending(code: str) -> str:
        """Detect line ending style from code.

        Args:
            code: Source code content

        Returns:
            Line ending string

        """
        return "\r\n" if "\r\n" in code else "\n"

    @staticmethod
    def _count_indent_styles(lines: list[str]) -> tuple[int, int, list[int]]:
        """Count tabs vs spaces in indented lines.

        Args:
            lines: Code lines to analyze

        Returns:
            Tuple of (tab_count, space_count, space_sizes)

        """
        tab_count = 0
        space_count = 0
        space_sizes = []

        for line in lines:
            if not line or not line[0].isspace():
                continue

            leading = len(line) - len(line.lstrip())

            if line[0] == "\t":
                tab_count += 1
            elif line[0] == " ":
                space_count += 1
                space_sizes.append(leading)

        return tab_count, space_count, space_sizes

    @staticmethod
    def _determine_indent_style(
        tab_count: int,
        space_count: int,
        space_sizes: list[int],
        language: str | None,
    ) -> tuple[IndentStyle, int]:
        """Determine indent style and size from counts.

        Args:
            tab_count: Number of tab-indented lines
            space_count: Number of space-indented lines
            space_sizes: List of space indent sizes
            language: Optional language hint

        Returns:
            Tuple of (style, size)

        """
        if tab_count > space_count:
            return IndentStyle.TABS, 1

        if space_count > 0:
            size = (
                WhitespaceHandler._find_indent_size(space_sizes)
                if space_sizes
                else DEFAULT_INDENT_SIZES.get(language or "", 4)
            )
            return IndentStyle.SPACES, size

        # No indented lines found, use language defaults
        if language == "go":
            return IndentStyle.TABS, 1

        return IndentStyle.SPACES, DEFAULT_INDENT_SIZES.get(language or "", 4)

    @staticmethod
    def detect_indent(code: str, language: str | None = None) -> IndentConfig:
        """Detect indentation style from existing code.

        Args:
            code: Source code content
            language: Optional language hint

        Returns:
            IndentConfig with detected settings

        """
        lines = code.split("\n")
        line_ending = WhitespaceHandler._detect_line_ending(code)

        tab_count, space_count, space_sizes = WhitespaceHandler._count_indent_styles(
            lines
        )
        style, size = WhitespaceHandler._determine_indent_style(
            tab_count, space_count, space_sizes, language
        )

        return IndentConfig(style=style, size=size, line_ending=line_ending)

    @staticmethod
    def _find_indent_size(space_counts: list[int]) -> int:
        """Find the most likely indentation size from leading space counts."""
        if not space_counts:
            return 4

        # Calculate differences between consecutive indentation levels
        diffs = []
        for i in range(1, len(space_counts)):
            diff = abs(space_counts[i] - space_counts[i - 1])
            if diff > 0:
                diffs.append(diff)

        if not diffs:
            # Fall back to most common space count
            from collections import Counter

            counts = Counter(space_counts)
            return counts.most_common(1)[0][0] if counts else 4

        # Find GCD of differences (most likely indent size)
        from functools import reduce
        from math import gcd

        result = reduce(gcd, diffs)

        # Validate result (should be 2, 4, or 8)
        if result in {2, 4, 8}:
            return result
        if result == 1:
            return 4  # Default
        return result if result < 8 else 4

    @staticmethod
    def _styles_match(current: IndentConfig, target: IndentConfig) -> bool:
        """Check if indent styles already match.

        Args:
            current: Current indent config
            target: Target indent config

        Returns:
            True if styles match

        """
        return current.style == target.style and current.size == target.size

    @staticmethod
    def _calculate_indent_level(leading_ws: int, config: IndentConfig) -> int:
        """Calculate indent level from leading whitespace.

        Args:
            leading_ws: Number of leading whitespace chars
            config: Indent configuration

        Returns:
            Indent level

        """
        if config.style == IndentStyle.TABS:
            return leading_ws  # Each tab = 1 level
        return leading_ws // config.size

    @staticmethod
    def _apply_target_indent(indent_level: int, target_config: IndentConfig) -> str:
        """Apply target indentation to a line.

        Args:
            indent_level: Indentation level
            target_config: Target config

        Returns:
            Indentation string

        """
        if target_config.style == IndentStyle.TABS:
            return "\t" * indent_level
        return " " * (indent_level * target_config.size)

    @staticmethod
    def _normalize_line_indent(
        line: str, current_config: IndentConfig, target_config: IndentConfig
    ) -> str:
        """Normalize indentation for a single line.

        Args:
            line: Line to normalize
            current_config: Current indent config
            target_config: Target indent config

        Returns:
            Normalized line

        """
        if not line or not line[0].isspace():
            return line

        leading_ws = len(line) - len(line.lstrip())
        content = line.lstrip()

        indent_level = WhitespaceHandler._calculate_indent_level(
            leading_ws, current_config
        )
        new_indent = WhitespaceHandler._apply_target_indent(indent_level, target_config)

        return new_indent + content

    @staticmethod
    def normalize_indent(
        code: str,
        target_config: IndentConfig | None = None,
        language: str | None = None,
    ) -> str:
        """Normalize indentation to match target config.

        Args:
            code: Source code to normalize
            target_config: Target indentation config (detected if None)
            language: Language hint for defaults

        Returns:
            Code with normalized indentation

        """
        if not code:
            return code

        current_config = WhitespaceHandler.detect_indent(code, language)
        target_config = target_config or current_config

        # Early exit if styles already match
        if WhitespaceHandler._styles_match(current_config, target_config):
            if current_config.line_ending != target_config.line_ending:
                return code.replace(
                    current_config.line_ending, target_config.line_ending
                )
            return code

        # Normalize each line
        lines = code.split("\n")
        normalized_lines = [
            WhitespaceHandler._normalize_line_indent(
                line, current_config, target_config
            )
            for line in lines
        ]

        result = "\n".join(normalized_lines)

        # Normalize line endings
        if target_config.line_ending != "\n":
            result = result.replace("\n", target_config.line_ending)

        return result

    @staticmethod
    def auto_indent_block(
        code_block: str,
        base_indent: int,
        config: IndentConfig | None = None,
        language: str | None = None,
    ) -> str:
        """Auto-indent a code block to a specific level.

        Args:
            code_block: Code to indent
            base_indent: Base indentation level
            config: Indentation config (detected if None)
            language: Language hint

        Returns:
            Indented code block

        """
        if not config:
            config = WhitespaceHandler.detect_indent(code_block, language)
            # If no indent detected, use language defaults
            if config.style == IndentStyle.SPACES and config.size == 4 and language:
                default_size = DEFAULT_INDENT_SIZES.get(language, 4)
                if language == "go":
                    config = IndentConfig(
                        style=IndentStyle.TABS, size=1, line_ending=config.line_ending
                    )
                else:
                    config = IndentConfig(
                        style=config.style,
                        size=default_size,
                        line_ending=config.line_ending,
                    )

        # Generate base indentation string
        if config.style == IndentStyle.TABS:
            base_indent_str = "\t" * base_indent
        else:
            base_indent_str = " " * (base_indent * config.size)

        # Split into lines and indent each
        lines = code_block.split("\n")
        indented_lines = []

        for line in lines:
            if line.strip():  # Only indent non-empty lines
                indented_lines.append(base_indent_str + line)
            else:
                indented_lines.append("")  # Keep blank lines blank

        return "\n".join(indented_lines)

    @staticmethod
    def get_line_indent(line: str, config: IndentConfig) -> int:
        """Get the indentation level of a line.

        Args:
            line: Line of code
            config: Indentation config

        Returns:
            Indentation level (0 for no indent)

        """
        if not line or not line[0].isspace():
            return 0

        leading_ws = len(line) - len(line.lstrip())

        if config.style == IndentStyle.TABS:
            return leading_ws
        return leading_ws // config.size

    @staticmethod
    def _get_min_indent(lines: list[str], config: IndentConfig) -> int:
        """Get minimum indentation level from lines.

        Args:
            lines: Lines to analyze
            config: Indent config

        Returns:
            Minimum indent level

        """
        min_indent = float("inf")
        for line in lines:
            if line.strip():
                indent_level = WhitespaceHandler.get_line_indent(line, config)
                min_indent = min(min_indent, indent_level)

        return 0 if min_indent == float("inf") else int(min_indent)

    @staticmethod
    def _reindent_line(
        line: str, min_indent: int, new_base_indent: int, config: IndentConfig
    ) -> str:
        """Reindent a single line with new base indent.

        Args:
            line: Line to reindent
            min_indent: Minimum indent to subtract
            new_base_indent: New base indent level
            config: Indent config

        Returns:
            Reindented line

        """
        if not line.strip():
            return ""

        current_indent = WhitespaceHandler.get_line_indent(line, config)
        relative_indent = current_indent - min_indent
        total_indent = new_base_indent + relative_indent

        if config.style == IndentStyle.TABS:
            new_indent_str = "\t" * total_indent
        else:
            new_indent_str = " " * (total_indent * config.size)

        return new_indent_str + line.lstrip()

    @staticmethod
    def preserve_relative_indent(
        code_block: str,
        new_base_indent: int,
        config: IndentConfig | None = None,
        language: str | None = None,
    ) -> str:
        """Re-indent code block while preserving relative indentation.

        Args:
            code_block: Code to re-indent
            new_base_indent: New base indentation level
            config: Indentation config (detected if None)
            language: Language hint

        Returns:
            Re-indented code with preserved relative structure

        """
        if not code_block:
            return code_block

        if not config:
            config = WhitespaceHandler.detect_indent(code_block, language)
            if language == "go" and config.style != IndentStyle.TABS:
                config = IndentConfig(
                    style=IndentStyle.TABS, size=1, line_ending=config.line_ending
                )

        lines = code_block.split("\n")
        min_indent = WhitespaceHandler._get_min_indent(lines, config)

        result_lines = [
            WhitespaceHandler._reindent_line(line, min_indent, new_base_indent, config)
            for line in lines
        ]

        return "\n".join(result_lines)

    @staticmethod
    def strip_trailing_whitespace(code: str) -> str:
        """Remove trailing whitespace from all lines."""
        lines = code.split("\n")
        return "\n".join(line.rstrip() for line in lines)

    @staticmethod
    def ensure_final_newline(code: str) -> str:
        """Ensure file ends with exactly one newline."""
        code = code.rstrip("\n")
        return code + "\n"

    @staticmethod
    def clean_whitespace(
        code: str, config: IndentConfig | None = None, language: str | None = None
    ) -> str:
        """Comprehensive whitespace cleanup.

        Args:
            code: Source code
            config: Indentation config (detected if None)
            language: Language hint

        Returns:
            Cleaned code

        """
        if not config:
            config = WhitespaceHandler.detect_indent(code, language)

        # Normalize indentation
        code = WhitespaceHandler.normalize_indent(code, config, language)

        # Strip trailing whitespace
        code = WhitespaceHandler.strip_trailing_whitespace(code)

        # Ensure final newline
        code = WhitespaceHandler.ensure_final_newline(code)

        # Remove multiple consecutive blank lines (max 2)
        return re.sub(r"\n{4,}", "\n\n\n", code)

