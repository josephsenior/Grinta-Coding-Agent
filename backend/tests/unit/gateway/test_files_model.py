"""Tests for backend.gateway.files upload response schema."""

from __future__ import annotations

import json

from backend.gateway.files import POSTUploadFilesModel


def test_post_upload_files_model_round_trip() -> None:
    m = POSTUploadFilesModel(
        file_urls=["https://example/a.png"],
        skipped_files=["bad.bin"],
    )
    data = json.loads(m.model_dump_json())
    assert data["file_urls"] == ["https://example/a.png"]
    assert data["skipped_files"] == ["bad.bin"]
