"""Hallucination detection and self-correction for production reliability.

This module implements industry-standard techniques used by Devin, Cursor, and other
leading AI coding tools to detect when an agent claims to perform an action without
actually executing the corresponding tool.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from backend.core.logger import FORGE_logger as logger
from backend.events.action.files import FileEditAction

if TYPE_CHECKING:
    from backend.events.action import Action


class HallucinationDetector:
    """Detects when agent claims actions without executing tools.

    Industry leaders like Devin and Cursor use similar systems to ensure
    reliability and prevent user frustration from hallucinated actions.

    Detection strategies:
    1. Text pattern matching - detect claims like "I created file.py"
    2. Tool execution tracking - verify tools were actually called
    3. State reconciliation - compare claimed vs actual file system state
    """

    # Patterns that indicate file creation claims
    FILE_CREATION_PATTERNS = [
        r"I (?:created|made|wrote|generated|built)\s+(?:a\s+)?(?:file\s+)?[\w/.-]+\.[\w]+",
        r"I've (?:created|made|written|generated)\s+(?:a\s+)?(?:file\s+)?[\w/.-]+\.[\w]+",
        r"(?:Created|Made|Wrote|Generated)\s+(?:a\s+)?(?:file\s+)?[\w/.-]+\.[\w]+",
        r"(?:The\s+)?file\s+[\w/.-]+\.[\w]+\s+(?:is|has been)\s+(?:created|saved|written)",
        r"saved\s+(?:as|to|at)\s+[\w/.-]+\.[\w]+",
    ]

    # Patterns that indicate file editing claims
    FILE_EDIT_PATTERNS = [
        r"I (?:edited|modified|updated|changed)\s+[\w/.-]+\.[\w]+",
        r"I've (?:edited|modified|updated)\s+[\w/.-]+\.[\w]+",
        r"(?:Updated|Modified|Edited|Changed)\s+[\w/.-]+\.[\w]+",
    ]

    # Patterns that indicate code execution claims
    CODE_EXEC_PATTERNS = [
        r"I (?:ran|executed|run)\s+",
        r"I've (?:run|executed)\s+",
        r"(?:Ran|Executed|Running)\s+",
    ]

    def __init__(self):
        """Initialize the hallucination detector."""
        self.detection_enabled = True
        self.false_positive_threshold = 0.7  # Confidence threshold to trigger alert

    def detect_text_hallucination(
        self, llm_response_text: str, tools_called: list[str], actions: list[Action]
    ) -> dict:
        """Detect if LLM claimed actions without executing tools.

        Args:
            llm_response_text: The text content from LLM response
            tools_called: List of tool names that were actually called
            actions: List of Action objects that were created

        Returns:
            Detection result dictionary with:
            - hallucinated: bool
            - confidence: float (0.0-1.0)
            - claimed_operations: list[str]
            - missing_tools: list[str]
            - severity: str ("low", "medium", "high", "critical")

        """
        if not self.detection_enabled:
            return {"hallucinated": False}

        hallucinations = []

        # Check for file creation claims
        creation_hallucination = self._detect_file_creation_hallucination(
            llm_response_text, tools_called, actions
        )
        if creation_hallucination:
            hallucinations.append(creation_hallucination)

        # Check for file edit claims
        edit_hallucination = self._detect_file_edit_hallucination(
            llm_response_text, tools_called, actions
        )
        if edit_hallucination:
            hallucinations.append(edit_hallucination)

        # Check for code execution claims
        exec_hallucination = self._detect_code_exec_hallucination(
            llm_response_text, tools_called, actions
        )
        if exec_hallucination:
            hallucinations.append(exec_hallucination)

        # Aggregate results
        if not hallucinations:
            return {"hallucinated": False}

        # Determine severity based on number and type of hallucinations
        severity = self._calculate_severity(hallucinations)

        return {
            "hallucinated": True,
            "confidence": max(h["confidence"] for h in hallucinations),
            "claimed_operations": [h["claim"] for h in hallucinations],
            "missing_tools": list(
                {tool for h in hallucinations for tool in h["missing_tools"]}
            ),
            "severity": severity,
            "details": hallucinations,
        }

    def _detect_file_creation_hallucination(
        self, text: str, tools_called: list[str], actions: list[Action]
    ) -> dict | None:
        """Detect file creation claims without tool calls."""
        # Check if text contains file creation claims
        for pattern in self.FILE_CREATION_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                claim = match.group(0)

                # Check if edit_file or str_replace_editor was called
                file_tools = ["edit_file", "str_replace_editor"]
                if not any(tool in tools_called for tool in file_tools):
                    # Check actions list too
                    if not any(isinstance(a, FileEditAction) for a in actions):
                        logger.warning(
                            "Hallucination detected: Claimed '%s' without tool call",
                            claim,
                        )
                        return {
                            "type": "file_creation",
                            "claim": claim,
                            "confidence": 0.9,
                            "missing_tools": file_tools,
                        }

        return None

    def _detect_file_edit_hallucination(
        self, text: str, tools_called: list[str], actions: list[Action]
    ) -> dict | None:
        """Detect file edit claims without tool calls."""
        for pattern in self.FILE_EDIT_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                claim = match.group(0)

                file_tools = ["edit_file", "str_replace_editor"]
                if not any(tool in tools_called for tool in file_tools):
                    if not any(isinstance(a, FileEditAction) for a in actions):
                        logger.warning(
                            "Hallucination detected: Claimed '%s' without tool call",
                            claim,
                        )
                        return {
                            "type": "file_edit",
                            "claim": claim,
                            "confidence": 0.85,
                            "missing_tools": file_tools,
                        }

        return None

    def _detect_code_exec_hallucination(
        self, text: str, tools_called: list[str], actions: list[Action]
    ) -> dict | None:
        """Detect code execution claims without tool calls."""
        for pattern in self.CODE_EXEC_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                claim = match.group(0)

                exec_tools = ["execute_bash"]
                if not any(tool in tools_called for tool in exec_tools):
                    # Lower confidence since "I ran" could be conversational
                    return {
                        "type": "code_execution",
                        "claim": claim,
                        "confidence": 0.6,
                        "missing_tools": exec_tools,
                    }

        return None

    def _calculate_severity(self, hallucinations: list[dict]) -> str:
        """Calculate overall severity of hallucinations.

        Args:
            hallucinations: List of hallucination detection results

        Returns:
            Severity level: "low", "medium", "high", or "critical"

        """
        if not hallucinations:
            return "none"

        max_confidence = max(h["confidence"] for h in hallucinations)
        count = len(hallucinations)

        # File operations are critical
        has_file_hallucination = any(
            h["type"] in ("file_creation", "file_edit") for h in hallucinations
        )

        if has_file_hallucination and max_confidence > 0.85:
            return "critical"
        if has_file_hallucination or (count > 2):
            return "high"
        if max_confidence > 0.7:
            return "medium"
        return "low"

    def generate_correction_prompt(
        self, detection_result: dict, original_request: str
    ) -> str:
        """Generate a prompt to correct the hallucination.

        Args:
            detection_result: Result from detect_text_hallucination()
            original_request: The original user request

        Returns:
            Correction prompt for the agent

        """
        if not detection_result.get("hallucinated"):
            return ""

        claimed_ops = detection_result["claimed_operations"]
        missing_tools = detection_result["missing_tools"]

        return f"""⚠️ HALLUCINATION DETECTED - AUTO-CORRECTION REQUIRED

You claimed the following operations:
{chr(10).join(f"  - {op}" for op in claimed_ops)}

But you did NOT execute the required tools:
{chr(10).join(f"  - {tool}" for tool in missing_tools)}

CRITICAL: You must ACTUALLY EXECUTE the tools, not just claim you did.

Original user request: {original_request}

Please RETRY with ACTUAL tool execution:
1. Call the required tool (e.g., edit_file, execute_bash)
2. Wait for the observation/result
3. Verify the result with a second tool call
4. Report the ACTUAL verification output

Do this NOW."""
