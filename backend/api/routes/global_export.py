"""Global export/import for all user data."""

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from backend.api.shared import config

router = APIRouter(prefix="/api/v1/global-export")
logger = logging.getLogger(__name__)


class GlobalExportData(BaseModel):
    """Container for all exportable data."""

    version: str = Field(
        default="1.0.0", min_length=1, description="Export format version"
    )
    exported_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        min_length=1,
        description="ISO timestamp of export",
    )
    memories: list[dict] = Field(default_factory=list, description="Exported memories")
    templates: list[dict] = Field(
        default_factory=list, description="Exported conversation templates"
    )
    settings: dict = Field(default_factory=dict, description="Exported settings")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")

    @field_validator("version", "exported_at")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="field")


def _load_json_files(directory: str) -> list[dict]:
    """Load all JSON files from a specified directory.

    Recursively discovers and parses all .json files in the target directory
    within the workspace base path. Errors loading individual files are logged
    but do not halt the operation.

    Args:
        directory: The relative directory path within workspace_base
            (e.g., "memories", "templates").

    Returns:
        list[dict]: A list of parsed JSON objects. Returns an empty list if
            the directory does not exist or contains no valid JSON files.

    Raises:
        No exceptions raised; errors are logged at exception level.

    """
    workspace_base = Path(config.workspace_base or ".")
    dir_path = workspace_base / directory

    if not dir_path.exists():
        return []

    data = []
    for file_path in dir_path.glob("*.json"):
        try:
            with open(file_path, encoding="utf-8") as f:
                data.append(json.load(f))
        except Exception as e:
            logger.exception("Error loading %s: %s", file_path, e)

    return data


def _save_json_files(directory: str, data: list[dict]) -> tuple[int, int]:
    """Save JSON data to files in a specified directory.

    Persists a collection of JSON-serializable objects to individual files
    in the target directory. Each object must have an "id" field used as
    the filename. Tracks import vs update counts based on pre-existence.

    Args:
        directory: The relative directory path within workspace_base
            where files will be saved (e.g., "memories").
        data: List of dictionaries to persist. Each item must
            contain at least an "id" key. Items without "id" are skipped.

    Returns:
        tuple[int, int]: A tuple of (imported_count, updated_count) where:
            - imported_count: Number of new files created
            - updated_count: Number of existing files overwritten

    Raises:
        No exceptions raised; errors are logged at exception level.

    """
    workspace_base = Path(config.workspace_base or ".")
    dir_path = workspace_base / directory
    dir_path.mkdir(parents=True, exist_ok=True)

    imported = 0
    updated = 0

    for item in data:
        try:
            item_id = item.get("id")
            if not item_id:
                continue

            file_path = dir_path / f"{item_id}.json"
            exists = file_path.exists()

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(item, f, indent=2)

            if exists:
                updated += 1
            else:
                imported += 1
        except Exception as e:
            logger.exception("Error saving item: %s", e)

    return imported, updated


@router.get("/")
async def export_all_data() -> JSONResponse:
    r"""Export all user data as a downloadable JSON backup file.

    Aggregates all memories, templates, and settings
    into a single GlobalExportData structure and returns it as an HTTP
    attachment with timestamped filename for download.

    Returns:
        JSONResponse: Status 200 OK with:
            - Content-Type: application/json
            - Headers: Content-Disposition with timestamped filename
            - Body: GlobalExportData model serialized to JSON

    Raises:
        HTTPException: 500 Internal Server Error if data loading or
            JSON serialization fails. Error detail included in response.

    Examples:
        >>> curl -X GET http://localhost:3000/api/global-export/ \\
        ...     -o forge_backup_20250106_143022.json

    """
    try:
        export_data = GlobalExportData(
            version="1.0.0",
            memories=_load_json_files("memories"),
            templates=_load_json_files("templates"),
            metadata={
                "total_memories": len(_load_json_files("memories")),
                "total_templates": len(_load_json_files("templates")),
            },
        )

        return JSONResponse(
            content=json.loads(export_data.model_dump_json(indent=2)),
            headers={
                "Content-Disposition": f'attachment; filename="FORGE_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"',
            },
        )
    except Exception as e:
        logger.exception("Error exporting data: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/")
async def import_all_data(data: GlobalExportData) -> dict[str, dict[str, int]]:
    r"""Import all user data from a backup file.

    Restores user data from a previously exported GlobalExportData structure.
    Processes memories and templates in sequence,
    creating new files or updating existing ones.

    Args:
        data: GlobalExportData containing collections of:
            - memories (list[dict]): Memory entries
            - templates (list[dict]): Document templates

    Returns:
        dict[str, dict[str, int]]: Import results organized by category:
        {
            "memories": {"imported": int, "updated": int},
            "templates": {"imported": int, "updated": int}
        }

    Raises:
        HTTPException: 500 Internal Server Error if import/save operations fail.

    Examples:
        >>> curl -X POST http://localhost:3000/api/global-export/ \\
        ...     -H "Content-Type: application/json" \\
        ...     -d @forge_backup_20250106_143022.json

    """
    try:
        # Import memories
        mem_imported, mem_updated = _save_json_files("memories", data.memories)
        results = {"memories": {"imported": mem_imported, "updated": mem_updated}}

        # Import templates
        temp_imported, temp_updated = _save_json_files("templates", data.templates)
        results["templates"] = {"imported": temp_imported, "updated": temp_updated}

        logger.info("Import complete: %s", results)
        return results
    except Exception as e:
        logger.exception("Error importing data: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
