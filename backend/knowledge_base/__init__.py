"""Knowledge module for document storage and retrieval."""

from backend.knowledge_base.manager import KnowledgeBaseManager
from backend.storage.data_models.knowledge_base import (
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
    KnowledgeBaseSearchResult,
    KnowledgeBaseSettings,
)

__all__ = [
    "KnowledgeBaseManager",
    "KnowledgeBaseCollection",
    "KnowledgeBaseDocument",
    "KnowledgeBaseSearchResult",
    "KnowledgeBaseSettings",
]
