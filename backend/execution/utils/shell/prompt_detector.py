"""Intelligent Interactive Prompt Detection and Auto-Response System.

This module provides automatic detection and response to interactive prompts
during command execution, enabling true autonomous agent behavior.

The system works in layers:
1. Detect when a command is waiting for user input
2. Identify the type of prompt (confirmation, password, selection, etc.)
3. Automatically provide appropriate input
4. Resume command execution transparently

This allows agents to handle interactive commands without manual intervention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from backend.core.logger import app_logger as logger


class PromptType(Enum):
    """Types of interactive prompts we can detect and handle."""

    YES_NO_CONFIRMATION = 'yes_no'  # (y/n), (Y/n), yes/no prompts
    OK_PROCEED = 'ok_proceed'  # "Ok to proceed?", "Continue?"
    PASSWORD = 'password'  # Password prompts
    SELECTION = 'selection'  # Menu selections (1, 2, 3...)
    PRESS_KEY = 'press_key'  # "Press any key to continue"
    OVERWRITE = 'overwrite'  # File overwrite confirmations
    SUDO_PASSWORD = 'sudo_password'  # sudo password prompts
    LICENSE_AGREEMENT = 'license'  # License acceptance
    UNKNOWN = 'unknown'


@dataclass
class PromptPattern:
    """Pattern definition for detecting interactive prompts."""

    pattern: str  # Regex pattern to match
    prompt_type: PromptType
    response: str  # What to auto-type
    description: str  # Human-readable description
    confidence: float = 1.0  # Confidence score (0.0-1.0)

    def matches(self, text: str) -> bool:
        """Check if the pattern matches the given text."""
        return bool(re.search(self.pattern, text, re.IGNORECASE | re.MULTILINE))


# Comprehensive prompt patterns for common scenarios
PROMPT_PATTERNS = [
    # npm/npx package installation prompts
    PromptPattern(
        pattern=r'Ok to proceed\?\s*\(y\)',
        prompt_type=PromptType.OK_PROCEED,
        response='y\n',
        description='npm/npx package installation confirmation',
        confidence=1.0,
    ),
    # Generic yes/no confirmations
    PromptPattern(
        pattern=r'\(y/n\)\s*[\?\:]?\s*$',
        prompt_type=PromptType.YES_NO_CONFIRMATION,
        response='y\n',
        description='Generic yes/no confirmation',
        confidence=0.9,
    ),
    PromptPattern(
        pattern=r'\(Y/n\)\s*[\?\:]?\s*$',
        prompt_type=PromptType.YES_NO_CONFIRMATION,
        response='Y\n',
        description='Yes (default) confirmation',
        confidence=0.9,
    ),
    PromptPattern(
        pattern=r'\[y/N\]\s*[\?\:]?\s*$',
        prompt_type=PromptType.YES_NO_CONFIRMATION,
        response='y\n',
        description='Yes/No (default) confirmation',
        confidence=0.9,
    ),
    # "Continue?" prompts
    PromptPattern(
        pattern=r'(Continue|Proceed|Do you want to continue)\?',
        prompt_type=PromptType.OK_PROCEED,
        response='y\n',
        description='Continue/Proceed confirmation',
        confidence=0.85,
    ),
    # apt/apt-get prompts
    PromptPattern(
        pattern=r'Do you want to continue\?\s*\[Y/n\]',
        prompt_type=PromptType.YES_NO_CONFIRMATION,
        response='Y\n',
        description='apt-get installation confirmation',
        confidence=1.0,
    ),
    # File overwrite confirmations
    PromptPattern(
        pattern=r'(overwrite|replace)\s+.*\?\s*\(y/n\)',
        prompt_type=PromptType.OVERWRITE,
        response='y\n',
        description='File overwrite confirmation',
        confidence=0.9,
    ),
    # Press any key to continue
    PromptPattern(
        pattern=r'Press\s+(any\s+)?key\s+to\s+continue',
        prompt_type=PromptType.PRESS_KEY,
        response='\n',
        description='Press key to continue',
        confidence=1.0,
    ),
    # License agreements
    PromptPattern(
        pattern=r'Do you accept the license (terms|agreement)\?',
        prompt_type=PromptType.LICENSE_AGREEMENT,
        response='yes\n',
        description='License acceptance',
        confidence=0.95,
    ),
    # Git prompts
    PromptPattern(
        pattern=r'Are you sure you want to continue connecting.*\(yes/no(/\[fingerprint\])?\)\?',
        prompt_type=PromptType.YES_NO_CONFIRMATION,
        response='yes\n',
        description='SSH fingerprint confirmation',
        confidence=1.0,
    ),
    # Generic confirmation prompts
    PromptPattern(
        pattern=r'Are you sure you want to.*\?\s*\[y/N\]',
        prompt_type=PromptType.YES_NO_CONFIRMATION,
        response='y\n',
        description='Command confirmation',
        confidence=0.85,
    ),
    # Python pip prompts
    PromptPattern(
        pattern=r'Proceed\s+\(y/n\)\?',
        prompt_type=PromptType.OK_PROCEED,
        response='y\n',
        description='pip installation confirmation',
        confidence=0.9,
    ),
    # Homebrew prompts
    PromptPattern(
        pattern=r'Press RETURN to continue or any other key to abort',
        prompt_type=PromptType.PRESS_KEY,
        response='\n',
        description='Homebrew installation continue',
        confidence=1.0,
    ),
]


class InteractivePromptDetector:
    """Detects interactive prompts in command output and provides appropriate responses.

    This class analyzes terminal output to identify when a command is waiting
    for user input and automatically provides the appropriate response to
    enable autonomous agent operation.
    """

    def __init__(
        self, enable_auto_response: bool = True, min_confidence: float = 0.8
    ) -> None:
        """Initialize the prompt detector.

        Args:
            enable_auto_response: Whether to enable automatic responses
            min_confidence: Minimum confidence threshold for auto-response (0.0-1.0)

        """
        self.enable_auto_response = enable_auto_response
        self.min_confidence = min_confidence
        self.patterns = PROMPT_PATTERNS

    def detect_prompt(
        self, output: str, last_n_lines: int = 10
    ) -> PromptPattern | None:
        """Detect if the output contains an interactive prompt.

        Args:
            output: Command output to analyze
            last_n_lines: Number of recent lines to check (prompts usually at end)

        Returns:
            PromptPattern if detected, None otherwise

        """
        if not output or not output.strip():
            return None

        # Strip ANSI escape sequences to prevent them from interfering with regex matching
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        output = ansi_escape.sub('', output)

        # Focus on the last N lines where prompts typically appear
        lines = output.split('\n')
        recent_output = '\n'.join(lines[-last_n_lines:])

        # Try to match against known patterns
        for pattern in self.patterns:
            if pattern.confidence >= self.min_confidence and pattern.matches(
                recent_output
            ):
                logger.info(
                    '🤖 Auto-detected interactive prompt: %s (confidence: %s)',
                    pattern.description,
                    pattern.confidence,
                )
                return pattern

        return None

    def _looks_like_prompt(self, text: str) -> bool:
        """Heuristic check for prompt-like patterns.

        Returns True if the text looks like an interactive prompt even if
        we don't have a specific pattern for it.
        """
        prompt_indicators = [
            r'[\?\:]\s*$',  # Ends with ? or :
            r'\[.*\]\s*$',  # Ends with [options]
            r'\(.*\)\s*[\?\:]?\s*$',  # Ends with (options)?
            r'(enter|type|press|input|select|choose)\s+',  # Action verbs
        ]

        last_line = text.strip().split('\n')[-1].strip()
        return any(
            re.search(indicator, last_line, re.IGNORECASE)
            for indicator in prompt_indicators
        )

    def should_auto_respond(self, pattern: PromptPattern | None) -> bool:
        """Determine if we should automatically respond to this prompt.

        Args:
            pattern: The detected prompt pattern

        Returns:
            True if auto-response is enabled and safe

        """
        if not self.enable_auto_response or not pattern:
            return False

        # Don't auto-respond to password prompts (security risk)
        if pattern.prompt_type in [PromptType.PASSWORD, PromptType.SUDO_PASSWORD]:
            logger.warning(
                '🔒 Password prompt detected - auto-response disabled for security'
            )
            return False

        # Only auto-respond if confidence is above threshold
        return pattern.confidence >= self.min_confidence

    def get_response(self, pattern: PromptPattern) -> str:
        """Get the appropriate response for a detected prompt.

        Args:
            pattern: The detected prompt pattern

        Returns:
            The response string to send

        """
        return pattern.response


def detect_interactive_prompt(output: str) -> tuple[bool, str | None]:
    """Convenience function to detect prompts and get responses.

    Args:
        output: Command output to analyze

    Returns:
        Tuple of (is_prompt_detected, response_to_send)

    """
    detector = InteractivePromptDetector()
    pattern = detector.detect_prompt(output)

    if pattern and detector.should_auto_respond(pattern):
        return (True, detector.get_response(pattern))

    return (False, None)


# Common command modifications to prefer non-interactive mode
NONINTERACTIVE_COMMAND_TRANSFORMS = {
    # npm/npx commands
    r'^npx\s+': 'npx --yes ',
    r'^npm\s+install': 'npm install --yes',
    # apt/apt-get commands
    r'^apt\s+install': 'apt install -y',
    r'^apt-get\s+install': 'apt-get install -y',
    r'^apt\s+upgrade': 'apt upgrade -y',
    r'^apt-get\s+upgrade': 'apt-get upgrade -y',
}


def suggest_noninteractive_command(command: str) -> str | None:
    """Suggest a non-interactive version of a command if available.

    Args:
        command: The original command

    Returns:
        Modified command string or None if no transformation available

    """
    command = command.strip()

    for pattern, replacement in NONINTERACTIVE_COMMAND_TRANSFORMS.items():
        if re.match(pattern, command):
            # Check if non-interactive flag already present
            if (
                '--yes' in command
                or '-y' in command
                or '--force' in command
                or '-f' in command
            ):
                return None  # Already non-interactive

            modified = re.sub(pattern, replacement, command)
            if modified != command:
                logger.info('💡 Suggested non-interactive command: %s', modified)
                return modified

    return None
