"""API routes for Knowledge Base management."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator

from backend.core.constants import (
    KNOWLEDGE_BASE_DESCRIPTION_MAX_LENGTH,
    KNOWLEDGE_BASE_MAX_FILE_SIZE,
    KNOWLEDGE_BASE_NAME_MAX_LENGTH,
    KNOWLEDGE_BASE_RELEVANCE_THRESHOLD_DEFAULT,
    KNOWLEDGE_BASE_SEARCH_TOP_K_DEFAULT,
    KNOWLEDGE_BASE_SEARCH_TOP_K_MAX,
)
from backend.knowledge import KnowledgeBaseManager
from backend.gateway.utils.responses import error, success
from backend.persistence.data_models.knowledge_base import (
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
    KnowledgeBaseSearchResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge-base", tags=["knowledge-base"])


# Request/Response models


class CreateCollectionRequest(BaseModel):
    """Request to create a new collection."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=KNOWLEDGE_BASE_NAME_MAX_LENGTH,
        description="Collection name",
    )
    description: str | None = Field(
        None,
        max_length=KNOWLEDGE_BASE_DESCRIPTION_MAX_LENGTH,
        description="Collection description",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate name is non-empty using type-safe validation."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="name")


class UpdateCollectionRequest(BaseModel):
    """Request to update a collection."""

    name: str | None = None
    description: str | None = None


class SearchRequest(BaseModel):
    """Request to search the knowledge base."""

    query: str = Field(..., min_length=1, description="Search query string")
    collection_ids: list[str] | None = Field(
        None, description="Collection IDs to search in (None = all)"
    )
    top_k: int = Field(
        default=KNOWLEDGE_BASE_SEARCH_TOP_K_DEFAULT,
        ge=1,
        le=KNOWLEDGE_BASE_SEARCH_TOP_K_MAX,
        description="Number of top results to return",
    )
    relevance_threshold: float = Field(
        default=KNOWLEDGE_BASE_RELEVANCE_THRESHOLD_DEFAULT,
        ge=0.0,
        le=1.0,
        description="Minimum relevance score (0.0-1.0)",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        """Validate query is non-empty using type-safe validation."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="query")


class CollectionResponse(BaseModel):
    """Response containing collection data."""

    id: str
    name: str
    description: str | None
    document_count: int
    total_size_bytes: int
    total_size_mb: float
    created_at: str
    updated_at: str


class DocumentResponse(BaseModel):
    """Response containing document data."""

    id: str
    collection_id: str
    filename: str
    file_size_bytes: int
    file_size_kb: float
    mime_type: str
    content_preview: str | None
    chunk_count: int
    uploaded_at: str


class SearchResultResponse(BaseModel):
    """Response containing search result."""

    document_id: str
    collection_id: str
    filename: str
    chunk_content: str
    relevance_score: float


class BulkUploadRequest(BaseModel):
    """Request to upload multiple documents in one call."""

    collection_id: str
    documents: list[BulkDocumentInput]


class BulkDocumentInput(BaseModel):
    """Individual document in a bulk upload."""

    filename: str = Field(..., min_length=1, description="Document filename")
    content: str = Field(..., min_length=1, description="Document content")
    mime_type: str = Field(
        default="text/plain", description="MIME type of the document"
    )

    @field_validator("filename", "content")
    @classmethod
    def validate_required_strings(cls, v: str) -> str:
        """Validate required string fields are non-empty."""
        from backend.core.type_safety.type_safety import validate_non_empty_string

        return validate_non_empty_string(v, name="field")


class BulkUploadResultItem(BaseModel):
    """Result of uploading a single document in bulk."""

    filename: str
    success: bool
    document_id: str | None = None
    error: str | None = None


class BulkUploadResponse(BaseModel):
    """Response from bulk document upload."""

    total: int
    successful: int
    failed: int
    results: list[BulkUploadResultItem]


# Helper functions


def _get_kb_manager(user_id: str = "default") -> KnowledgeBaseManager:
    """Create and return a KnowledgeBaseManager instance for a user.

    Factory function to instantiate a knowledge base manager scoped to a specific
    user. Enables isolation of knowledge bases across multiple users in the system.

    Args:
        user_id: User identifier for the knowledge base scope (default: "default")

    Returns:
        KnowledgeBaseManager: Initialized manager for the specified user

    Raises:
        ValueError: If user_id is empty string

    Example:
        kb_manager = _get_kb_manager("user123")
        collections = kb_manager.list_collections()

    """
    return KnowledgeBaseManager(user_id=user_id)


def _collection_to_response(collection: KnowledgeBaseCollection) -> CollectionResponse:
    """Convert KnowledgeBaseCollection model to API response format.

    Transforms internal collection data model into a response object suitable
    for HTTP endpoints, converting timestamps to ISO format and calculating
    size in megabytes from bytes.

    Args:
        collection: Internal KnowledgeBaseCollection model

    Returns:
        CollectionResponse with formatted fields ready for JSON serialization

    Example:
        collection = kb_manager.get_collection("coll123")
        response = _collection_to_response(collection)
        # response.total_size_mb is calculated from bytes

    """
    return CollectionResponse(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        document_count=collection.document_count,
        total_size_bytes=collection.total_size_bytes,
        total_size_mb=round(collection.total_size_bytes / (1024 * 1024), 2),
        created_at=collection.created_at.isoformat(),
        updated_at=collection.updated_at.isoformat(),
    )


def _document_to_response(document: KnowledgeBaseDocument) -> DocumentResponse:
    """Convert KnowledgeBaseDocument model to API response format.

    Transforms internal document data model into a response object suitable
    for HTTP endpoints, converting timestamps to ISO format and calculating
    size in kilobytes from bytes.

    Args:
        document: Internal KnowledgeBaseDocument model

    Returns:
        DocumentResponse with formatted fields ready for JSON serialization

    Example:
        doc = kb_manager.get_document("doc123")
        response = _document_to_response(doc)
        # response.file_size_kb is calculated from bytes

    """
    return DocumentResponse(
        id=document.id,
        collection_id=document.collection_id,
        filename=document.filename,
        file_size_bytes=document.file_size_bytes,
        file_size_kb=round(document.file_size_bytes / 1024, 2),
        mime_type=document.mime_type,
        content_preview=document.content_preview,
        chunk_count=document.chunk_count,
        uploaded_at=document.uploaded_at.isoformat(),
    )


def _search_result_to_response(
    result: KnowledgeBaseSearchResult,
) -> SearchResultResponse:
    """Convert KnowledgeBaseSearchResult to API response format.

    Transforms internal search result into a response object for HTTP endpoints,
    rounding the relevance score to 3 decimal places for clarity.

    Args:
        result: Internal KnowledgeBaseSearchResult from search operation

    Returns:
        SearchResultResponse with relevance_score rounded to 3 decimals

    Example:
        results = kb_manager.search("query")
        response = [_search_result_to_response(r) for r in results]

    """
    return SearchResultResponse(
        document_id=result.document_id,
        collection_id=result.collection_id,
        filename=result.filename,
        chunk_content=result.chunk_content,
        relevance_score=round(result.relevance_score, 3),
    )


# Collection endpoints


@router.post(
    "/collections",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    request: CreateCollectionRequest,
    user_id: str = "default",
) -> CollectionResponse:
    """Create a new knowledge base collection."""
    try:
        kb_manager = _get_kb_manager(user_id)
        collection = kb_manager.create_collection(
            name=request.name,
            description=request.description,
        )
        logger.info("Created collection: %s (ID: %s)", collection.name, collection.id)
        return _collection_to_response(collection)
    except Exception as e:
        logger.error("Failed to create collection: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create collection: {str(e)}",
        )


@router.get("/collections", response_model=list[CollectionResponse])
async def list_collections(user_id: str = "default") -> list[CollectionResponse]:
    """List all collections for the user."""
    try:
        kb_manager = _get_kb_manager(user_id)
        collections = kb_manager.list_collections()
        return [_collection_to_response(c) for c in collections]
    except Exception as e:
        logger.error("Failed to list collections: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list collections: {str(e)}",
        )


@router.get("/collections/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: str,
    user_id: str = "default",
) -> CollectionResponse:
    """Get a collection by ID."""
    try:
        kb_manager = _get_kb_manager(user_id)
        collection = kb_manager.get_collection(collection_id)
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )
        return _collection_to_response(collection)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get collection: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get collection: {str(e)}",
        )


@router.patch("/collections/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: str,
    request: UpdateCollectionRequest,
    user_id: str = "default",
) -> CollectionResponse:
    """Update a collection."""
    try:
        kb_manager = _get_kb_manager(user_id)
        collection = kb_manager.update_collection(
            collection_id=collection_id,
            name=request.name,
            description=request.description,
        )
        if not collection:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )
        logger.info("Updated collection: %s (ID: %s)", collection.name, collection.id)
        return _collection_to_response(collection)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update collection: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update collection: {str(e)}",
        )


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    user_id: str = "default",
):
    """Delete a collection and all its documents."""
    try:
        kb_manager = _get_kb_manager(user_id)
        success = kb_manager.delete_collection(collection_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )
        logger.info("Deleted collection: %s", collection_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete collection: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete collection: {str(e)}",
        )


# Document endpoints


@router.post(
    "/collections/{collection_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    collection_id: str,
    file: UploadFile = File(...),
    user_id: str = "default",
) -> DocumentResponse:
    """Upload a document to a collection."""
    try:
        # Validate file size
        MAX_FILE_SIZE = KNOWLEDGE_BASE_MAX_FILE_SIZE
        content = await file.read()

        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size is {MAX_FILE_SIZE / (1024 * 1024)}MB",
            )

        # Decode content (assume UTF-8 text for MVP)
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be a valid UTF-8 text file",
            )

        # Add document
        kb_manager = _get_kb_manager(user_id)
        document = await kb_manager.async_add_document(
            collection_id=collection_id,
            filename=file.filename or "untitled",
            content=text_content,
            mime_type=file.content_type or "text/plain",
        )

        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Collection {collection_id} not found",
            )

        logger.info(
            "Uploaded document: %s to collection %s", document.filename, collection_id
        )
        return _document_to_response(document)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to upload document: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload document: {str(e)}",
        )


@router.get(
    "/collections/{collection_id}/documents", response_model=list[DocumentResponse]
)
async def list_documents(
    collection_id: str,
    user_id: str = "default",
) -> list[DocumentResponse]:
    """List all documents in a collection."""
    try:
        kb_manager = _get_kb_manager(user_id)
        documents = kb_manager.list_documents(collection_id)
        return [_document_to_response(d) for d in documents]
    except Exception as e:
        logger.error("Failed to list documents: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list documents: {str(e)}",
        )


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    user_id: str = "default",
) -> DocumentResponse:
    """Get a document by ID."""
    try:
        kb_manager = _get_kb_manager(user_id)
        document = kb_manager.get_document(document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} not found",
            )
        return _document_to_response(document)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get document: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get document: {str(e)}",
        )


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    user_id: str = "default",
):
    """Delete a document."""
    try:
        kb_manager = _get_kb_manager(user_id)
        success = kb_manager.delete_document(document_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} not found",
            )
        logger.info("Deleted document: %s", document_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete document: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete document: {str(e)}",
        )


# Search endpoint


@router.post("/search", response_model=list[SearchResultResponse])
async def search_knowledge_base(
    request: SearchRequest,
    user_id: str = "default",
) -> list[SearchResultResponse]:
    """Search the knowledge base."""
    try:
        kb_manager = _get_kb_manager(user_id)
        results = await kb_manager.async_search(
            query=request.query,
            collection_ids=request.collection_ids,
            top_k=request.top_k,
            relevance_threshold=request.relevance_threshold,
        )
        return [_search_result_to_response(r) for r in results]
    except Exception as e:
        logger.error("Failed to search knowledge base: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search knowledge base: {str(e)}",
        )


# Stats endpoint


@router.get("/stats")
async def get_stats(user_id: str = "default") -> dict[str, Any]:
    """Get knowledge base statistics."""
    try:
        kb_manager = _get_kb_manager(user_id)
        return kb_manager.get_stats()
    except Exception as e:
        logger.error("Failed to get stats: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stats: {str(e)}",
        )


# Bulk upload endpoint


@router.post(
    "/collections/{collection_id}/documents/bulk", status_code=status.HTTP_201_CREATED
)
async def bulk_upload_documents(
    collection_id: str,
    files: list[UploadFile] = File(...),
    user_id: str = "default",
    max_concurrent: int = 5,
) -> Any:
    """Upload multiple documents to a collection in parallel.

    Processes documents concurrently with bounded parallelism to improve
    throughput while avoiding resource exhaustion. Returns detailed results
    for each document including success/failure status.

    Args:
        collection_id: Target collection ID
        files: List of files to upload
        user_id: User identifier (default: "default")
        max_concurrent: Maximum concurrent uploads (default: 5)

    Returns:
        Standardized response with bulk upload results

    Example:
        POST /api/knowledge-base/collections/{id}/documents/bulk
        Files: [file1.txt, file2.md, file3.py]
        Response: {
            "status": "ok",
            "data": {
                "total": 3,
                "successful": 2,
                "failed": 1,
                "results": [...]
            }
        }
    """
    MAX_FILE_SIZE = KNOWLEDGE_BASE_MAX_FILE_SIZE

    # Verify collection exists
    kb_manager = _get_kb_manager(user_id)
    collection = kb_manager.get_collection(collection_id)
    if not collection:
        return error(
            message=f"Collection {collection_id} not found",
            status_code=status.HTTP_404_NOT_FOUND,
            error_code="COLLECTION_NOT_FOUND",
        )

    results: list[BulkUploadResultItem] = []

    async def process_file(file: UploadFile) -> BulkUploadResultItem:
        """Process a single file upload."""
        try:
            content_bytes = await file.read()

            # Check file size
            if len(content_bytes) > MAX_FILE_SIZE:
                return BulkUploadResultItem(
                    filename=file.filename or "untitled",
                    success=False,
                    error=f"File too large (max {MAX_FILE_SIZE / (1024 * 1024)}MB)",
                )

            # Decode content
            try:
                text_content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return BulkUploadResultItem(
                    filename=file.filename or "untitled",
                    success=False,
                    error="File must be valid UTF-8 text",
                )

            # Add document via async manager method
            document = await kb_manager.async_add_document(
                collection_id=collection_id,
                filename=file.filename or "untitled",
                content=text_content,
                mime_type=file.content_type or "text/plain",
            )

            if not document:
                return BulkUploadResultItem(
                    filename=file.filename or "untitled",
                    success=False,
                    error="Failed to create document",
                )

            return BulkUploadResultItem(
                filename=file.filename or "untitled",
                success=True,
                document_id=document.id,
            )
        except Exception as e:
            logger.error("Failed to process file %s: %s", file.filename, e)
            return BulkUploadResultItem(
                filename=file.filename or "untitled",
                success=False,
                error=str(e),
            )

    # Process files with bounded concurrency
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_process(file: UploadFile) -> BulkUploadResultItem:
        async with semaphore:
            return await process_file(file)

    # Execute all uploads concurrently with limit
    results = await asyncio.gather(
        *[bounded_process(f) for f in files],
        return_exceptions=False,
    )

    # Calculate summary
    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    logger.info(
        "Bulk upload to collection %s: %s/%s successful, %s failed",
        collection_id,
        successful,
        len(files),
        failed,
    )

    return success(
        data={
            "total": len(files),
            "successful": successful,
            "failed": failed,
            "results": [r.model_dump() for r in results],
        },
        message=f"Processed {len(files)} files: {successful} successful, {failed} failed",
        status_code=status.HTTP_201_CREATED,
    )
