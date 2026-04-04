"""Knowledge Base data models for document storage and retrieval."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    pass


class KnowledgeBaseCollection(BaseModel):
    """A collection of related documents in the knowledge base."""

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=1,
        description='Unique collection identifier',
    )
    user_id: str = Field(
        ..., min_length=1, description='User ID who owns this collection'
    )
    name: str = Field(..., min_length=1, max_length=200, description='Collection name')
    description: str | None = Field(
        None, max_length=1000, description='Optional collection description'
    )
    document_count: int = Field(
        0, ge=0, description='Number of documents in this collection'
    )
    total_size_bytes: int = Field(
        0, ge=0, description='Total size of all documents in bytes'
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description='Collection creation timestamp',
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description='Last update timestamp',
    )

    @field_validator('id', 'user_id', 'name')
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='field')


class KnowledgeBaseDocument(BaseModel):
    """A document stored in the knowledge base."""

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=1,
        description='Unique document identifier',
    )
    collection_id: str = Field(
        ..., min_length=1, description='ID of the collection this document belongs to'
    )
    filename: str = Field(
        ..., min_length=1, max_length=500, description='Original filename'
    )
    content_hash: str = Field(
        ..., min_length=1, description='SHA256 hash for deduplication'
    )
    file_size_bytes: int = Field(..., ge=0, description='File size in bytes')
    mime_type: str = Field(..., min_length=1, description='MIME type of the document')
    content_preview: str | None = Field(
        None, max_length=500, description='First 500 characters for display'
    )
    chunk_count: int = Field(0, ge=0, description='Number of chunks in vector store')
    uploaded_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description='Upload timestamp',
    )

    @field_validator('id', 'collection_id', 'filename', 'content_hash', 'mime_type')
    @classmethod
    def validate_non_empty_doc(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='field')


class DocumentChunk(BaseModel):
    """A chunk of a document for vector storage."""

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=1,
        description='Unique chunk identifier',
    )
    document_id: str = Field(..., min_length=1, description='ID of the parent document')
    chunk_index: int = Field(
        ..., ge=0, description='Zero-based index of this chunk in the document'
    )
    content: str = Field(..., min_length=1, description='Chunk content text')
    metadata: dict[str, str | int | float] = Field(
        default_factory=dict, description='Additional chunk metadata'
    )

    @field_validator('id', 'document_id', 'content')
    @classmethod
    def validate_non_empty_chunk(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='field')


class KnowledgeBaseSearchResult(BaseModel):
    """A search result from the knowledge base."""

    document_id: str = Field(
        ..., min_length=1, description='ID of the matching document'
    )
    collection_id: str = Field(
        ..., min_length=1, description='ID of the collection containing this document'
    )
    filename: str = Field(
        ..., min_length=1, description='Filename of the matching document'
    )
    chunk_content: str = Field(
        ..., min_length=1, description='Content of the matching chunk'
    )
    relevance_score: float = Field(
        ..., ge=0.0, le=1.0, description='Relevance score (0.0 to 1.0)'
    )
    metadata: dict[str, str | int | float] = Field(
        default_factory=dict, description='Additional result metadata'
    )

    @field_validator('document_id', 'collection_id', 'filename', 'chunk_content')
    @classmethod
    def validate_non_empty_res(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name='field')


class KnowledgeBaseSettings(BaseModel):
    """User settings for knowledge base feature."""

    enabled: bool = Field(True, description='Whether knowledge base is enabled')
    active_collection_ids: list[str] = Field(
        default_factory=list, description='IDs of active collections to search'
    )
    search_top_k: int = Field(
        5, ge=1, le=100, description='Number of results to return'
    )
    relevance_threshold: float = Field(
        0.7, ge=0.0, le=1.0, description='Minimum relevance score (0.0 to 1.0)'
    )
    auto_search: bool = Field(True, description='Auto-search KB in chat conversations')
    search_strategy: str = Field(
        'hybrid', description="Search strategy: 'hybrid', 'semantic', or 'keyword'"
    )
