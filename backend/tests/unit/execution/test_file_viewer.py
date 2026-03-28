"""Tests for backend.execution.utils.file_viewer module.

Targets the 0% (21 missed lines) coverage gap.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from backend.execution.utils.file_viewer import generate_file_viewer_html


def _write_temp(suffix: str, content: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, content)
    os.close(fd)
    return path


class TestGenerateFileViewerHtml:
    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported file extension"):
            generate_file_viewer_html("/tmp/test.txt")

    def test_file_not_found_raises(self):
        with pytest.raises(ValueError, match="File not found"):
            generate_file_viewer_html("/nonexistent/path/file.pdf")

    def test_pdf_generates_html(self):
        path = _write_temp(".pdf", b"%PDF-1.4 fake pdf content")
        try:
            html = generate_file_viewer_html(path)
            assert "<!DOCTYPE html>" in html
            assert "File Viewer" in html
            assert ".pdf" in html
        finally:
            os.unlink(path)

    def test_png_generates_html(self):
        path = _write_temp(".png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        try:
            html = generate_file_viewer_html(path)
            assert "<!DOCTYPE html>" in html
            assert "image/png" in html
        finally:
            os.unlink(path)

    def test_jpg_generates_html(self):
        path = _write_temp(".jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        try:
            html = generate_file_viewer_html(path)
            assert "<!DOCTYPE html>" in html
        finally:
            os.unlink(path)

    def test_jpeg_generates_html(self):
        path = _write_temp(".jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        try:
            html = generate_file_viewer_html(path)
            assert "<!DOCTYPE html>" in html
        finally:
            os.unlink(path)

    def test_gif_generates_html(self):
        path = _write_temp(".gif", b"GIF89a" + b"\x00" * 20)
        try:
            html = generate_file_viewer_html(path)
            assert "<!DOCTYPE html>" in html
        finally:
            os.unlink(path)

    def test_html_contains_base64_for_images(self):
        path = _write_temp(".png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        try:
            html = generate_file_viewer_html(path)
            assert "fileBase64" in html
        finally:
            os.unlink(path)

    def test_py_extension_rejected(self):
        with pytest.raises(ValueError, match="Unsupported"):
            generate_file_viewer_html("/tmp/test.py")

    def test_no_extension_rejected(self):
        with pytest.raises(ValueError, match="Unsupported"):
            generate_file_viewer_html("/tmp/noext")
