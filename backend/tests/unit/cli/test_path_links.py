"""Tests for :mod:`backend.cli.display.path_links`."""

from __future__ import annotations

from backend.cli.display.path_links import file_uri_for_path, linkify_plain


def test_linkify_plain_preserves_non_path_text() -> None:
    t = linkify_plain('hello world', link_files=True, link_urls=False)
    assert t.plain == 'hello world'


def test_file_uri_for_path_relative_resolves() -> None:
    uri = file_uri_for_path('backend/cli/path_links.py')
    assert uri is not None
    assert uri.startswith('file://')


def test_linkify_plain_includes_link_span_for_existing_file() -> None:
    t = linkify_plain('see backend/cli/path_links.py for logic', link_files=True)
    assert 'backend/cli/path_links.py' in t.plain
    assert any(getattr(s.style, 'link', None) is not None for s in t.spans if s.style)
