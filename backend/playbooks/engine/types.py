"""Pydantic models and enums describing App playbooks metadata and responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from backend.core.config.mcp_config import MCPConfig


class PlaybookType(str, Enum):
    """Type of playbook."""

    KNOWLEDGE = 'knowledge'
    REPO_KNOWLEDGE = 'repo'
    TASK = 'task'


class InputMetadata(BaseModel):
    """Metadata for task playbook inputs."""

    name: str
    description: str


class PlaybookMetadata(BaseModel):
    """Metadata for all playbooks."""

    name: str = 'default'
    type: PlaybookType = Field(default=PlaybookType.REPO_KNOWLEDGE)
    version: str = Field(default='1.0.0')
    agent: str = Field(default='Orchestrator')
    triggers: list[str] = Field(default_factory=list)
    inputs: list[InputMetadata] = Field(default_factory=list)
    mcp_tools: MCPConfig | None = None
    #: When True, only exact trigger containment checks apply.
    strict_trigger_matching: bool = False

    @field_validator('triggers')
    @classmethod
    def _validate_triggers(cls, triggers: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for trigger in triggers:
            value = trigger.strip()
            if not value:
                msg = 'triggers must not contain empty values'
                raise ValueError(msg)
            folded = value.casefold()
            if folded in seen:
                msg = f'duplicate trigger not allowed: {value}'
                raise ValueError(msg)
            seen.add(folded)
            normalized.append(value)
        return normalized

    @field_validator('inputs')
    @classmethod
    def _validate_inputs(cls, inputs: list[InputMetadata]) -> list[InputMetadata]:
        seen: set[str] = set()
        for input_meta in inputs:
            folded = input_meta.name.casefold()
            if folded in seen:
                msg = f'duplicate input name not allowed: {input_meta.name}'
                raise ValueError(msg)
            seen.add(folded)
        return inputs


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
    triggers: list[str] = Field(default_factory=list)
    vcs_provider: str | None = None


# Resolve any forward references after imports are available
PlaybookMetadata.model_rebuild()
PlaybookResponse.model_rebuild()
PlaybookContentResponse.model_rebuild()
