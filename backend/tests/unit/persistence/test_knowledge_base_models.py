"""Tests for backend.persistence.data_models.knowledge_base — KB data models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.persistence.data_models.knowledge_base import (
    DocumentChunk,
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
    KnowledgeBaseSearchResult,
    KnowledgeBaseSettings,
)


# ── KnowledgeBaseCollection ──────────────────────────────────────────


class TestKnowledgeBaseCollection:
    def test_valid_defaults(self):
        c = KnowledgeBaseCollection(user_id="u1", name="My KB")
        assert c.user_id == "u1"
        assert c.name == "My KB"
        assert c.document_count == 0
        assert c.total_size_bytes == 0
        assert c.description is None
        assert c.id  # auto-generated uuid

    def test_custom_values(self):
        c = KnowledgeBaseCollection(
            id="custom-id",
            user_id="u2",
            name="Docs",
            description="Important docs",
            document_count=5,
            total_size_bytes=1024,
        )
        assert c.id == "custom-id"
        assert c.description == "Important docs"
        assert c.document_count == 5
        assert c.total_size_bytes == 1024

    def test_empty_user_id_rejected(self):
        with pytest.raises((ValidationError, ValueError)):
            KnowledgeBaseCollection(user_id="", name="KB")

    def test_empty_name_rejected(self):
        with pytest.raises((ValidationError, ValueError)):
            KnowledgeBaseCollection(user_id="u1", name="")

    def test_name_max_length(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseCollection(user_id="u1", name="A" * 201)

    def test_description_max_length(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseCollection(user_id="u1", name="KB", description="X" * 1001)

    def test_document_count_negative(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseCollection(user_id="u1", name="KB", document_count=-1)

    def test_total_size_bytes_negative(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseCollection(user_id="u1", name="KB", total_size_bytes=-1)

    def test_unique_ids(self):
        c1 = KnowledgeBaseCollection(user_id="u1", name="A")
        c2 = KnowledgeBaseCollection(user_id="u1", name="B")
        assert c1.id != c2.id


# ── KnowledgeBaseDocument ────────────────────────────────────────────


class TestKnowledgeBaseDocument:
    def test_valid(self):
        d = KnowledgeBaseDocument(
            collection_id="c1",
            filename="readme.md",
            content_hash="abc123",
            file_size_bytes=512,
            mime_type="text/markdown",
        )
        assert d.collection_id == "c1"
        assert d.filename == "readme.md"
        assert d.chunk_count == 0
        assert d.content_preview is None

    def test_with_preview(self):
        d = KnowledgeBaseDocument(
            collection_id="c1",
            filename="doc.txt",
            content_hash="hash",
            file_size_bytes=0,
            mime_type="text/plain",
            content_preview="Hello world",
            chunk_count=3,
        )
        assert d.content_preview == "Hello world"
        assert d.chunk_count == 3

    def test_empty_filename_rejected(self):
        with pytest.raises((ValidationError, ValueError)):
            KnowledgeBaseDocument(
                collection_id="c1",
                filename="",
                content_hash="h",
                file_size_bytes=0,
                mime_type="text/plain",
            )

    def test_empty_content_hash_rejected(self):
        with pytest.raises((ValidationError, ValueError)):
            KnowledgeBaseDocument(
                collection_id="c1",
                filename="f.txt",
                content_hash="",
                file_size_bytes=0,
                mime_type="text/plain",
            )

    def test_negative_file_size(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseDocument(
                collection_id="c1",
                filename="f.txt",
                content_hash="h",
                file_size_bytes=-1,
                mime_type="text/plain",
            )

    def test_content_preview_max_length(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseDocument(
                collection_id="c1",
                filename="f.txt",
                content_hash="h",
                file_size_bytes=0,
                mime_type="text/plain",
                content_preview="X" * 501,
            )

    def test_filename_max_length(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseDocument(
                collection_id="c1",
                filename="A" * 501,
                content_hash="h",
                file_size_bytes=0,
                mime_type="text/plain",
            )


# ── DocumentChunk ────────────────────────────────────────────────────


class TestDocumentChunk:
    def test_valid(self):
        ch = DocumentChunk(
            document_id="d1",
            chunk_index=0,
            content="Some text chunk.",
        )
        assert ch.document_id == "d1"
        assert ch.chunk_index == 0
        assert ch.metadata == {}

    def test_with_metadata(self):
        ch = DocumentChunk(
            document_id="d1",
            chunk_index=2,
            content="Data",
            metadata={"page": 3, "section": "intro"},
        )
        assert ch.metadata["page"] == 3

    def test_empty_content_rejected(self):
        with pytest.raises((ValidationError, ValueError)):
            DocumentChunk(document_id="d1", chunk_index=0, content="")

    def test_empty_document_id_rejected(self):
        with pytest.raises((ValidationError, ValueError)):
            DocumentChunk(document_id="", chunk_index=0, content="text")

    def test_negative_chunk_index(self):
        with pytest.raises(ValidationError):
            DocumentChunk(document_id="d1", chunk_index=-1, content="text")


# ── KnowledgeBaseSearchResult ────────────────────────────────────────


class TestKnowledgeBaseSearchResult:
    def test_valid(self):
        r = KnowledgeBaseSearchResult(
            document_id="d1",
            collection_id="c1",
            filename="file.py",
            chunk_content="def foo():",
            relevance_score=0.85,
        )
        assert r.relevance_score == 0.85
        assert r.metadata == {}

    def test_score_boundaries(self):
        KnowledgeBaseSearchResult(
            document_id="d1",
            collection_id="c1",
            filename="f",
            chunk_content="c",
            relevance_score=0.0,
        )
        KnowledgeBaseSearchResult(
            document_id="d1",
            collection_id="c1",
            filename="f",
            chunk_content="c",
            relevance_score=1.0,
        )

    def test_score_too_low(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseSearchResult(
                document_id="d1",
                collection_id="c1",
                filename="f",
                chunk_content="c",
                relevance_score=-0.1,
            )

    def test_score_too_high(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseSearchResult(
                document_id="d1",
                collection_id="c1",
                filename="f",
                chunk_content="c",
                relevance_score=1.1,
            )

    def test_empty_chunk_content_rejected(self):
        with pytest.raises((ValidationError, ValueError)):
            KnowledgeBaseSearchResult(
                document_id="d1",
                collection_id="c1",
                filename="f",
                chunk_content="",
                relevance_score=0.5,
            )


# ── KnowledgeBaseSettings ───────────────────────────────────────────


class TestKnowledgeBaseSettings:
    def test_defaults(self):
        s = KnowledgeBaseSettings()
        assert s.enabled is True
        assert s.active_collection_ids == []
        assert s.search_top_k == 5
        assert s.relevance_threshold == 0.7
        assert s.auto_search is True
        assert s.search_strategy == "hybrid"

    def test_custom(self):
        s = KnowledgeBaseSettings(
            enabled=False,
            active_collection_ids=["c1", "c2"],
            search_top_k=10,
            relevance_threshold=0.5,
            auto_search=False,
            search_strategy="semantic",
        )
        assert s.search_top_k == 10
        assert len(s.active_collection_ids) == 2

    def test_search_top_k_min(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseSettings(search_top_k=0)

    def test_search_top_k_max(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseSettings(search_top_k=101)

    def test_relevance_threshold_min(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseSettings(relevance_threshold=-0.1)

    def test_relevance_threshold_max(self):
        with pytest.raises(ValidationError):
            KnowledgeBaseSettings(relevance_threshold=1.1)
