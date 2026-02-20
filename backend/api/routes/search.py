"""Global search API endpoints.

Provides search across conversations, files, and other resources.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from backend.core.logger import forge_logger as logger
from backend.api.user_auth import get_user_id
from backend.api.utils import get_conversation_store
from backend.api.utils.responses import error, success
from backend.storage.data_models.conversation_metadata import ConversationMetadata

if TYPE_CHECKING:
    from backend.storage.conversation.conversation_store import ConversationStore
else:
    ConversationStore = Any

router = APIRouter(prefix="/api/v1/search", tags=["search"])


class SearchResult(BaseModel):
    """Search result item."""

    id: str = Field(..., min_length=1, description="Result identifier")
    type: str = Field(
        ..., min_length=1, description="Result type (e.g., 'conversation', 'file')"
    )
    title: str = Field(..., min_length=1, description="Result title")
    description: str | None = Field(None, description="Result description")
    url: str | None = Field(None, description="Result URL")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )

    @field_validator("id", "type", "title")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="field")


class SearchResponse(BaseModel):
    """Search response."""

    query: str = Field(..., min_length=1, description="Search query that was executed")
    results: dict[str, list[SearchResult]] = Field(
        default_factory=dict, description="Search results grouped by type"
    )
    total: int = Field(default=0, ge=0, description="Total number of results")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Validate query is non-empty using type-safe validation."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="query")


async def _search_conversations(
    conversation_store: ConversationStore | None,
    user_id: str,
    query: str,
    limit: int = 10,
) -> list[SearchResult]:
    """Search conversations.

    Args:
        conversation_store: Conversation storage
        user_id: User identifier
        query: Search query
        limit: Maximum results

    Returns:
        List of search results
    """
    if not conversation_store:
        return []

    try:
        # Get all conversations and filter by query
        result_set = await conversation_store.search(page_id=None, limit=1000)
        conversations = result_set.results

        query_lower = query.lower()
        results = []

        for conv in conversations:
            if _matches_search_query(conv, query_lower):
                results.append(_create_search_result(conv))
                if len(results) >= limit:
                    break

        return results

    except Exception as e:
        logger.error("Error searching conversations: %s", e, exc_info=True)
        return []


def _matches_search_query(conv: ConversationMetadata, query_lower: str) -> bool:
    """Check if conversation matches search query."""
    title = (conv.title or "").lower()
    repo = (conv.selected_repository or "").lower()
    return query_lower in title or query_lower in repo


def _create_search_result(conv: ConversationMetadata) -> SearchResult:
    """Create a SearchResult from conversation metadata."""
    return SearchResult(
        id=conv.conversation_id,
        type="conversation",
        title=conv.title or "Untitled Conversation",
        description=f"Repository: {conv.selected_repository or 'N/A'}",
        url=f"/conversations/{conv.conversation_id}",
        metadata={
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
        },
    )


async def _search_files(
    user_id: str,
    query: str,
    limit: int = 10,
) -> list[SearchResult]:
    """Search files by name in the user's file store.

    Performs a case-insensitive substring match against file paths.

    Args:
        user_id: User identifier
        query: Search query (matched against file paths)
        limit: Maximum results

    Returns:
        List of search results matching the query
    """
    try:
        from backend.api.shared import file_store

        all_files = file_store.list("")
        query_lower = query.lower()
        results: list[SearchResult] = []

        for file_path in all_files:
            if query_lower in file_path.lower():
                # Determine a human-friendly title from the path
                name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
                results.append(
                    SearchResult(
                        id=file_path,
                        type="file",
                        title=name,
                        description=file_path,
                        url=f"/files/{file_path}",
                        metadata={"path": file_path},
                    )
                )
                if len(results) >= limit:
                    break

        return results

    except Exception as e:
        logger.error("Error searching files: %s", e, exc_info=True)
        return []


@router.get("")
async def global_search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    type: str = Query("all", description="Search type: conversations, files, all"),
    limit: int = Query(10, ge=1, le=100, description="Maximum results per type"),
    user_id: str = Depends(get_user_id),
    conversation_store: ConversationStore | None = Depends(get_conversation_store),
) -> JSONResponse:
    """Global search across all resources.

    Args:
        request: FastAPI request
        q: Search query
        type: Type of resources to search (conversations, files, all)
        limit: Maximum results per type
        user_id: User identifier (from dependency)
        conversation_store: Conversation store (from dependency)

    Returns:
        Search results
    """
    try:
        # Validate query using type-safe validation
        from backend.core.type_safety.type_safety import validate_non_empty_string

        try:
            query = validate_non_empty_string(q.strip(), name="query")
        except ValueError as e:
            return error(
                message=f"Search query validation failed: {e}",
                error_code="INVALID_QUERY",
                request=request,
                status_code=400,
            )
        results: dict[str, list[SearchResult]] = {}
        total = 0

        # Search conversations
        if type in ("conversations", "all"):
            conversation_results = await _search_conversations(
                conversation_store, user_id, query, limit=limit
            )
            results["conversations"] = conversation_results
            total += len(conversation_results)

        # Search files
        if type in ("files", "all"):
            file_results = await _search_files(user_id, query, limit=limit)
            results["files"] = file_results
            total += len(file_results)

        search_response = SearchResponse(
            query=query,
            results=results,
            total=total,
        )

        return success(
            data=search_response.model_dump(),
            request=request,
        )

    except Exception as e:
        logger.error("Error performing global search: %s", e, exc_info=True)
        return error(
            message="Search failed",
            error_code="SEARCH_ERROR",
            request=request,
            status_code=500,
        )
