"""Tests for backend.execution.server_utils — list path resolution and directory sorting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from backend.execution.server_utils import (
    _get_sorted_directory_entries,
    _resolve_list_path,
)


async def _fake_request(json_value: object | Exception) -> MagicMock:
    req = MagicMock()
    if isinstance(json_value, Exception):
        req.json = AsyncMock(side_effect=json_value)
    else:
        req.json = AsyncMock(return_value=json_value)
    return req


async def test_resolve_list_path_falls_back_to_cwd_on_json_error(tmp_path: Path) -> None:
    client = MagicMock()
    client.initial_cwd = str(tmp_path.resolve())
    req = await _fake_request(ValueError("bad json"))

    out = await _resolve_list_path(req, client)

    assert out == str(tmp_path.resolve())


async def test_resolve_list_path_empty_dict_uses_cwd(tmp_path: Path) -> None:
    client = MagicMock()
    client.initial_cwd = str(tmp_path.resolve())
    req = await _fake_request({})

    assert await _resolve_list_path(req, client) == str(tmp_path.resolve())


async def test_resolve_list_path_absolute_normalized(tmp_path: Path) -> None:
    sub = tmp_path / "nested"
    sub.mkdir(parents=True)
    client = MagicMock()
    client.initial_cwd = str(tmp_path.resolve())
    req = await _fake_request({"path": str(sub.resolve())})

    out = await _resolve_list_path(req, client)
    assert Path(out) == sub.resolve()


async def test_resolve_list_path_relative_joins_cwd(tmp_path: Path) -> None:
    sub = tmp_path / "rel"
    sub.mkdir()
    client = MagicMock()
    client.initial_cwd = str(tmp_path.resolve())
    req = await _fake_request({"path": "rel"})

    out = await _resolve_list_path(req, client)
    assert Path(out) == sub.resolve()


async def test_resolve_list_path_non_dict_json_uses_cwd(tmp_path: Path) -> None:
    client = MagicMock()
    client.initial_cwd = str(tmp_path.resolve())
    req = await _fake_request([1, 2, 3])

    assert await _resolve_list_path(req, client) == str(tmp_path.resolve())


def test_get_sorted_directory_entries_dirs_before_files(tmp_path: Path) -> None:
    d = tmp_path / "listing"
    d.mkdir()
    (d / "zebra_dir").mkdir()
    (d / "aaa.txt").write_text("x", encoding="utf-8")

    names = _get_sorted_directory_entries(str(d))
    assert names == ["zebra_dir", "aaa.txt"]


def test_get_sorted_directory_entries_case_insensitive_file_order(tmp_path: Path) -> None:
    d = tmp_path / "listing2"
    d.mkdir()
    (d / "B.txt").write_text("b", encoding="utf-8")
    (d / "a.txt").write_text("a", encoding="utf-8")

    names = _get_sorted_directory_entries(str(d))
    assert names == ["a.txt", "B.txt"]
