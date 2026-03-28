"""Data models for conversation templates."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TemplateCategory(str, Enum):
    """Categories for conversation templates."""

    DEBUG = "debug"
    REFACTOR = "refactor"
    DOCUMENT = "document"
    TEST = "test"
    REVIEW = "review"
    EXPLAIN = "explain"
    OPTIMIZE = "optimize"
    FIX_BUG = "fix_bug"
    ADD_FEATURE = "add_feature"
    CUSTOM = "custom"


class ConversationTemplate(BaseModel):
    """Represents a conversation template."""

    id: str = Field(..., min_length=1, description="Unique identifier")
    title: str = Field(..., min_length=1, max_length=200, description="Template title")
    description: str | None = Field(
        None, max_length=1000, description="Template description"
    )
    category: TemplateCategory = Field(
        default=TemplateCategory.CUSTOM, description="Template category"
    )
    prompt: str = Field(..., min_length=1, description="The initial prompt/message")
    icon: str | None = Field(None, description="Icon identifier")
    is_favorite: bool = Field(
        default=False, description="Whether template is favorited"
    )
    usage_count: int = Field(
        default=0, ge=0, description="Number of times template was used"
    )
    created_at: datetime = Field(
        default_factory=datetime.now, description="Creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.now, description="Last update timestamp"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("id", "title", "prompt")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="field")


class CreateTemplateRequest(BaseModel):
    """Request to create a template."""

    title: str = Field(..., min_length=1, max_length=200, description="Template title")
    description: str | None = Field(
        None, max_length=1000, description="Template description"
    )
    category: TemplateCategory = Field(
        default=TemplateCategory.CUSTOM, description="Template category"
    )
    prompt: str = Field(..., min_length=1, description="The initial prompt/message")
    icon: str | None = Field(None, description="Icon identifier")
    is_favorite: bool = Field(default=False, description="Whether to mark as favorite")

    @field_validator("title", "prompt")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="field")


class UpdateTemplateRequest(BaseModel):
    """Request to update a template."""

    title: str | None = None
    description: str | None = None
    category: TemplateCategory | None = None
    prompt: str | None = None
    icon: str | None = None
    is_favorite: bool | None = None
