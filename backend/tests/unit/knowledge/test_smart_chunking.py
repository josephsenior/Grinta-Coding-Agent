"""Unit tests for SmartChunker strategies."""

from __future__ import annotations

import json

from backend.knowledge.smart_chunking import SmartChunker


def test_get_file_type_from_extension() -> None:
    chunker = SmartChunker()
    assert chunker.get_file_type('module.py') == 'code'
    assert chunker.get_file_type('notes.md') == 'markdown'
    assert chunker.get_file_type('data.json') == 'json'
    assert chunker.get_file_type('config.yaml') == 'yaml'
    assert chunker.get_file_type(None) == 'text'


def test_get_chunk_params_uses_type_defaults() -> None:
    chunker = SmartChunker()
    code_size, code_overlap = chunker.get_chunk_params('app.py')
    json_size, json_overlap = chunker.get_chunk_params('data.json')
    assert code_size == SmartChunker.CHUNK_SIZES['code']
    assert json_size == SmartChunker.CHUNK_SIZES['json']
    assert code_overlap > json_overlap


def test_chunk_markdown_splits_on_headers() -> None:
    chunker = SmartChunker()
    content = '# Title\n\nintro\n\n## Section\n\nbody text\n'
    chunks = chunker.chunk_markdown(content, 'doc1', {'source': 'readme'})
    assert chunks
    assert all(chunk.document_id == 'doc1' for chunk in chunks)
    assert any('Title' in chunk.content or 'Section' in chunk.content for chunk in chunks)


def test_chunk_json_by_top_level_keys() -> None:
    chunker = SmartChunker()
    payload = {'users': [{'id': 1}], 'meta': {'version': 2}}
    chunks = chunker.chunk_json(json.dumps(payload), 'doc2', None)
    assert len(chunks) >= 2
    assert all('# ' in chunk.content for chunk in chunks)


def test_chunk_json_invalid_falls_back_to_text() -> None:
    chunker = SmartChunker()
    chunks = chunker.chunk_json('{not json', 'doc3', None)
    assert chunks
    assert chunks[0].document_id == 'doc3'


def test_chunk_yaml_document_splits() -> None:
    chunker = SmartChunker()
    content = '---\nname: first\n---\nname: second\n'
    chunks = chunker.chunk_yaml(content, 'doc4', None)
    assert chunks


def test_sliding_window_chunk_produces_multiple_chunks() -> None:
    chunker = SmartChunker()
    content = 'word ' * 400
    chunks = chunker._sliding_window_chunk(
        content, 'doc5', None, chunk_size=200, chunk_overlap=20
    )
    assert len(chunks) > 1
    assert chunks[0].chunk_index == 0
