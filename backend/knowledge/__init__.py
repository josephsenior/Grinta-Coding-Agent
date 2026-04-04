"""Knowledge module for document storage and retrieval."""

from backend.knowledge.knowledge_base_manager import KnowledgeBaseManager
from backend.persistence.data_models.knowledge_base import (
    KnowledgeBaseCollection,
    KnowledgeBaseDocument,
    KnowledgeBaseSearchResult,
    KnowledgeBaseSettings,
)

__all__ = [
    'KnowledgeBaseManager',
    'KnowledgeBaseCollection',
    'KnowledgeBaseDocument',
    'KnowledgeBaseSearchResult',
    'KnowledgeBaseSettings',
]
