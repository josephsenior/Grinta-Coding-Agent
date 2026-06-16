"""Unit tests for knowledge base vector hit helpers."""

from __future__ import annotations

from backend.knowledge.knowledge_base_manager import (
    _required_vector_text,
    _vector_hit_metadata,
)


def test_vector_hit_metadata_filters_reserved_and_non_scalars() -> None:
    result = {
        'step_id': 's1',
        'score': 0.9,
        'excerpt': 'hello',
        'document_id': 'doc-1',
        'chunk_index': 2,
        'filename': 'readme.md',
        'flag': True,
        'nested': {'x': 1},
    }
    metadata = _vector_hit_metadata(result)
    assert metadata == {
        'document_id': 'doc-1',
        'chunk_index': 2,
        'filename': 'readme.md',
    }


def test_required_vector_text_strips_and_rejects_invalid() -> None:
    assert _required_vector_text({'title': '  hello  '}, 'title') == 'hello'
    assert _required_vector_text({'title': ''}, 'title') is None
    assert _required_vector_text({'title': 42}, 'title') is None
    assert _required_vector_text({}, 'missing') is None
