"""API routes for conversation templates."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path as PathLib
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path

from backend.server.shared import config
from backend.storage.data_models.conversation_template import (
    ConversationTemplate,
    CreateTemplateRequest,
    TemplateCategory,
    UpdateTemplateRequest,
)

router = APIRouter(prefix="/api/templates")
logger = logging.getLogger(__name__)


def _get_templates_dir() -> PathLib:
    """Get templates directory."""
    workspace_base = PathLib(config.workspace_base or ".")
    templates_dir = workspace_base / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    return templates_dir


def _get_template_file(template_id: str) -> PathLib:
    """Get template file path."""
    return _get_templates_dir() / f"{template_id}.json"


def _load_template(template_id: str) -> ConversationTemplate | None:
    """Load a template."""
    try:
        file_path = _get_template_file(template_id)
        if not file_path.exists():
            return None
        with open(file_path, encoding="utf-8") as f:
            return ConversationTemplate(**json.load(f))
    except Exception as e:
        logger.exception("Error loading template %s: %s", template_id, e)
        return None


def _save_template(template: ConversationTemplate) -> None:
    """Save a template."""
    try:
        file_path = _get_template_file(template.id)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(template.model_dump(), f, indent=2, default=str)
    except Exception as e:
        logger.exception("Error saving template: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


def _load_all_templates() -> list[ConversationTemplate]:
    """Load all templates."""
    templates = []
    for file_path in _get_templates_dir().glob("*.json"):
        try:
            with open(file_path, encoding="utf-8") as f:
                templates.append(ConversationTemplate(**json.load(f)))
        except Exception as e:
            logger.exception("Error loading %s: %s", file_path, e)
    return templates


@router.get("/")
async def list_templates(
    category: TemplateCategory | None = None,
    is_favorite: bool | None = None,
) -> list[ConversationTemplate]:
    """List all templates."""
    templates = _load_all_templates()
    if category:
        templates = [t for t in templates if t.category == category]
    if is_favorite is not None:
        templates = [t for t in templates if t.is_favorite == is_favorite]
    templates.sort(key=lambda t: t.updated_at, reverse=True)
    return templates


@router.post("/", status_code=201)
async def create_template(request: CreateTemplateRequest) -> ConversationTemplate:
    """Create a new template."""
    template = ConversationTemplate(
        id=str(uuid4()),
        title=request.title,
        description=request.description,
        category=request.category,
        prompt=request.prompt,
        icon=request.icon,
        is_favorite=request.is_favorite,
        usage_count=0,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    _save_template(template)
    return template


@router.get("/{template_id}")
async def get_template(
    template_id: Annotated[str, Path(..., min_length=1, description="Template ID")],
) -> ConversationTemplate:
    """Get a template."""
    template = _load_template(template_id)
    if template:
        return template
    raise HTTPException(status_code=404, detail="Template not found")


@router.patch("/{template_id}")
async def update_template(
    template_id: Annotated[str, Path(..., min_length=1, description="Template ID")],
    request: UpdateTemplateRequest,
) -> ConversationTemplate:
    """Update a template."""
    template = _load_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if request.title is not None:
        template.title = request.title
    if request.description is not None:
        template.description = request.description
    if request.category is not None:
        template.category = request.category
    if request.prompt is not None:
        template.prompt = request.prompt
    if request.icon is not None:
        template.icon = request.icon
    if request.is_favorite is not None:
        template.is_favorite = request.is_favorite

    template.updated_at = datetime.now()
    _save_template(template)
    return template


@router.delete("/{template_id}", status_code=204, response_model=None)
async def delete_template(
    template_id: Annotated[str, Path(..., min_length=1, description="Template ID")],
) -> None:
    """Delete a template."""
    template = _load_template(template_id)
    if template:
        _get_template_file(template_id).unlink()
    else:
        raise HTTPException(status_code=404, detail="Template not found")


@router.post("/{template_id}/use")
async def track_template_usage(
    template_id: Annotated[str, Path(..., min_length=1, description="Template ID")],
) -> ConversationTemplate:
    """Track template usage."""
    template = _load_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    template.usage_count += 1
    template.updated_at = datetime.now()
    _save_template(template)
    return template
