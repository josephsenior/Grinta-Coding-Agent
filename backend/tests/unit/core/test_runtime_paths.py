from __future__ import annotations

import os
from pathlib import Path

from backend.core import runtime_paths as rp


def test_pin_grinta_runtime_paths_sets_log_root(
    monkeypatch, tmp_path: Path
) -> None:
    repo = tmp_path / 'grinta'
    (repo / 'backend').mkdir(parents=True)
    (repo / 'pyproject.toml').write_text('[project]\nname="x"\n', encoding='utf-8')
    monkeypatch.setenv('GRINTA_REPO_ROOT', str(repo))
    monkeypatch.delenv('GRINTA_LOG_ROOT', raising=False)

    root = rp.pin_grinta_runtime_paths()

    assert root == repo.resolve()
    assert os.environ['GRINTA_LOG_ROOT'] == str(repo / 'logs')
    assert (repo / 'logs' / 'workspaces').is_dir()
    assert (repo / 'logs' / 'launch.log').is_file()
