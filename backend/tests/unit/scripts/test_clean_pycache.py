"""Tests for scripts.dev.clean_pycache."""

from __future__ import annotations

from pathlib import Path

from scripts.dev.clean_pycache import clean_pycache


def test_clean_pycache_removes_dirs_and_files(tmp_path: Path) -> None:
    pkg = tmp_path / 'pkg'
    cache = pkg / '__pycache__'
    cache.mkdir(parents=True)
    (cache / 'mod.cpython-312.pyc').write_bytes(b'bytecode')
    (pkg / 'orphan.pyc').write_bytes(b'bytecode')

    removed_dirs, removed_files = clean_pycache(tmp_path)

    assert removed_dirs == 1
    assert removed_files == 1
    assert not cache.exists()
    assert not (pkg / 'orphan.pyc').exists()
