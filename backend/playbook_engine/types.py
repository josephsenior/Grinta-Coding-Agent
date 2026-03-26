"""Pydantic models and enums describing Forge playbooks metadata and responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from backend.core.config.mcp_config import MCPConfig


class PlaybookType(str, Enum):
    """Type of playbook."""

    KNOWLEDGE = "knowledge"
    REPO_KNOWLEDGE = "repo"
    TASK = "task"


class InputMetadata(BaseModel):
    """Metadata for task playbook inputs."""

    name: str
    description: str


class PlaybookMetadata(BaseModel):
    """Metadata for all playbooks."""

    name: str = "default"
    type: PlaybookType = Field(default=PlaybookType.REPO_KNOWLEDGE)
    version: str = Field(default="1.0.0")
    agent: str = Field(default="Orchestrator")
    triggers: list[str] = []
    inputs: list[InputMetadata] = []
    mcp_tools: MCPConfig | None = None
    #: When True, only explicit substring trigger matches apply (no word-overlap tier).
    strict_trigger_matching: bool = False


class PlaybookResponse(BaseModel):
    """Response model for playbooks endpoint.

    Note: This model only includes basic metadata that can be determined
    without parsing playbook content. Use the separate content API
    to get detailed playbook information.
    """

    name: str
    path: str
    created_at: datetime


class PlaybookContentResponse(BaseModel):
    """Response model for individual playbook content endpoint."""

    content: str
    path: str
    triggers: list[str] = []
    vcs_provider: str | None = None


# Resolve any forward references after imports are available
PlaybookMetadata.model_rebuild()
PlaybookResponse.model_rebuild()
PlaybookContentResponse.model_rebuild()
