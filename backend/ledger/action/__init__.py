"""Action event definitions emitted by App agents."""

from __future__ import annotations

from backend.core.enums import ActionConfirmationStatus, ActionSecurityRisk
from backend.ledger.action.action import Action
from backend.ledger.action.agent import (
    AgentRejectAction,
    AgentThinkAction,
    BlackboardAction,
    ChangeAgentStateAction,
    ClarificationRequestAction,
    CondensationAction,
    CondensationRequestAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    PlaybookFinishAction,
    ProposalAction,
    RecallAction,
    TaskTrackingAction,
    UncertaintyAction,
)
from backend.ledger.action.browse import BrowseInteractiveAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.empty import NullAction
from backend.ledger.action.files import (
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.ledger.action.mcp import MCPAction
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.action.message import (
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
    "BlackboardAction",
    "ChangeAgentStateAction",
    "ClarificationRequestAction",
    "CmdRunAction",
    "CondensationAction",
    "CondensationRequestAction",
    "BrowseInteractiveAction",
    "DelegateTaskAction",
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
    "TerminalInputAction",
    "TerminalReadAction",
    "TerminalRunAction",
    "UncertaintyAction",
]
