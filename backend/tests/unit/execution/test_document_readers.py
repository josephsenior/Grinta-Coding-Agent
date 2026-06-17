"""Tests for document text extraction helpers."""

from __future__ import annotations

import pytest

from backend.execution.document_readers import (
    extract_docx_text,
    extract_pdf_text,
    extract_pptx_text,
)


def test_extract_pdf_text_requires_documents_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == 'pypdf':
            raise ImportError('no pypdf')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', _import)
    with pytest.raises(RuntimeError, match='documents'):
        extract_pdf_text('sample.pdf')


def test_extract_docx_text_requires_documents_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == 'docx':
            raise ImportError('no docx')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', _import)
    with pytest.raises(RuntimeError, match='documents'):
        extract_docx_text('sample.docx')


def test_extract_pptx_text_requires_documents_extra(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _import(name, *args, **kwargs):
        if name == 'pptx':
            raise ImportError('no pptx')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', _import)
    with pytest.raises(RuntimeError, match='documents'):
        extract_pptx_text('sample.pptx')
