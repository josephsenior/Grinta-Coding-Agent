"""Action event definitions emitted by Forge agents."""

from __future__ import annotations

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk
from backend.events.action.action import Action
from backend.events.action.agent import (
    AgentRejectAction,
    AgentThinkAction,
    ChangeAgentStateAction,
    ClarificationRequestAction,
    EscalateToHumanAction,
    PlaybookFinishAction,
    ProposalAction,
    RecallAction,
    TaskTrackingAction,
    UncertaintyAction,
)
from backend.events.action.commands import CmdRunAction
from backend.events.action.empty import NullAction
from backend.events.action.files import (
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.events.action.mcp import MCPAction
from backend.events.action.message import (
    MessageAction,
    StreamingChunkAction,
    SystemMessageAction,
)

__all__ = [
    "Action",
    "ActionConfirmationStatus",
    "ActionSecurityRisk",
    "PlaybookFinishAction",
    "AgentRejectAction",
    "AgentThinkAction",
    "ChangeAgentStateAction",
    "ClarificationRequestAction",
    "CmdRunAction",
    "EscalateToHumanAction",
    "FileEditAction",
    "FileReadAction",
    "FileWriteAction",
    "MCPAction",
    "MessageAction",
    "NullAction",
    "ProposalAction",
    "RecallAction",
    "StreamingChunkAction",  # ⚡ CRITICAL FIX: Enable real-time LLM streaming!
    "SystemMessageAction",
    "TaskTrackingAction",
    "UncertaintyAction",
]
