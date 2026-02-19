"""Meta-cognition tools enabling the LLM to express uncertainty and seek guidance.

These tools allow the LLM to:
- Express uncertainty about its understanding or observations
- Propose options before committing to a path
- Request clarification proactively
- Escalate to human assistance when stuck
"""

from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.engines.orchestrator.contracts import ChatCompletionToolParam

# Tool names constants for consistent referencing
UNCERTAINTY_TOOL_NAME = "uncertainty"
PROPOSAL_TOOL_NAME = "proposal"
CLARIFICATION_TOOL_NAME = "clarification"
ESCALATE_TOOL_NAME = "escalate_to_human"


# ============================================================================
# Uncertainty Tool - express doubt without guessing
# ============================================================================

_UNCERTAINTY_DESCRIPTION = (
    "Use this tool when you are uncertain about something and want to flag your doubt "
    "rather than guessing or making assumptions. The system can then provide clarification, "
    "additional context, or help you switch strategy.\n\n"
    "Common use cases:\n"
    "1. When tool output looks strange or unexpected\n"
    "2. When you have multiple hypotheses but can't determine which is correct\n"
    "3. When you realize you don't have enough information to proceed\n"
    "4. When previous attempts have failed and you suspect you might be on the wrong track\n\n"
    "This is NOT for general thinking - use think() for that. Use uncertainty() when you "
    "want the system to be aware of your confidence level."
)


def create_uncertainty_tool() -> ChatCompletionToolParam:
    """Create the uncertainty tool for expressing doubt."""
    return create_tool_definition(
        name=UNCERTAINTY_TOOL_NAME,
        description=_UNCERTAINTY_DESCRIPTION,
        properties={
            "uncertainty_level": {
                "type": "number",
                "description": "Your confidence level from 0.0 (completely uncertain) to 1.0 (fully confident). Default is 0.5.",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "specific_concerns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of specific things you are uncertain about.",
            },
            "requested_information": {
                "type": "string",
                "description": "What information would help resolve your uncertainty?",
            },
            "thought": {
                "type": "string",
                "description": "Your explanation of why you are uncertain.",
            },
        },
        required=["thought"],
    )


# ============================================================================
# Proposal Tool - present options before committing
# ============================================================================

_PROPOSAL_DESCRIPTION = (
    "Use this tool when you want to propose different approaches before committing to one. "
    "This is especially useful for risky or irreversible actions where you'd like user feedback "
    "before proceeding.\n\n"
    "Common use cases:\n"
    "1. When multiple approaches are viable and you'd like to know user's preference\n"
    "2. Before making significant changes that might break things\n"
    "3. When you're unsure which solution is best and want guidance\n"
    "4. Before refactoring that could have unintended consequences\n\n"
    "The system will present your options and wait for user selection before proceeding."
)


def create_proposal_tool() -> ChatCompletionToolParam:
    """Create the proposal tool for presenting options."""
    return create_tool_definition(
        name=PROPOSAL_TOOL_NAME,
        description=_PROPOSAL_DESCRIPTION,
        properties={
            "options": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "approach": {"type": "string", "description": "Description of this approach"},
                        "pros": {"type": "array", "items": {"type": "string"}, "description": "Advantages of this approach"},
                        "cons": {"type": "array", "items": {"type": "string"}, "description": "Disadvantages or risks"},
                    },
                    "required": ["approach"],
                },
                "description": "List of proposed options to choose from.",
            },
            "recommended": {
                "type": "integer",
                "description": "Index of the option you recommend (0-based).",
            },
            "rationale": {
                "type": "string",
                "description": "Why you are proposing these options.",
            },
            "thought": {
                "type": "string",
                "description": "Your explanation of the tradeoffs.",
            },
        },
        required=["options", "rationale"],
    )


# ============================================================================
# Clarification Tool - ask before assuming
# ============================================================================

_CLARIFICATION_DESCRIPTION = (
    "Use this tool when you need clarification from the user before proceeding. "
    "This helps avoid wasted work due to incorrect assumptions.\n\n"
    "Common use cases:\n"
    "1. Ambiguous instructions that could have multiple meanings\n"
    "2. When you're unsure what the user meant by something\n"
    "3. When the task scope is unclear\n"
    "4. When you need to know user preferences for styling, architecture, etc.\n\n"
    "The system will pause and ask the user for clarification before continuing."
)


def create_clarification_tool() -> ChatCompletionToolParam:
    """Create the clarification tool for requesting user input."""
    return create_tool_definition(
        name=CLARIFICATION_TOOL_NAME,
        description=_CLARIFICATION_DESCRIPTION,
        properties={
            "question": {
                "type": "string",
                "description": "The question you need answered to proceed.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional multiple choice options (if applicable).",
            },
            "context": {
                "type": "string",
                "description": "Why you need this clarification - what ambiguity you encountered.",
            },
            "thought": {
                "type": "string",
                "description": "Your reasoning about what the user might mean.",
            },
        },
        required=["question"],
    )


# ============================================================================
# Escalate Tool - request human assistance
# ============================================================================

_ESCALATE_DESCRIPTION = (
    "Use this tool when you need human assistance. This is appropriate when:\n"
    "1. You've tried multiple approaches without success\n"
    "2. The task requires knowledge or access you don't have\n"
    "3. You're stuck in a loop despite various strategies\n"
    "4. The task requires decisions only a human can make\n\n"
    "This is NOT a failure - it's a smart strategy when human insight is needed. "
    "The system will escalate to a human operator with your context."
)


def create_escalate_tool() -> ChatCompletionToolParam:
    """Create the escalate to human tool."""
    return create_tool_definition(
        name=ESCALATE_TOOL_NAME,
        description=_ESCALATE_DESCRIPTION,
        properties={
            "reason": {
                "type": "string",
                "description": "Why you are requesting human assistance.",
            },
            "attempts_made": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Summary of approaches you've already tried.",
            },
            "specific_help_needed": {
                "type": "string",
                "description": "What kind of help would resolve this.",
            },
            "thought": {
                "type": "string",
                "description": "Your explanation of why this needs human input.",
            },
        },
        required=["reason"],
    )
