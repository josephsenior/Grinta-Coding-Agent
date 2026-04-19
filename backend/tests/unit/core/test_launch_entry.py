from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import launch.entry as launcher


def test_main_prepends_entry_root_before_run_path(monkeypatch, tmp_path: Path) -> None:
    entry_file = tmp_path / 'backend' / 'cli' / 'entry.py'
    entry_file.parent.mkdir(parents=True)
    entry_file.write_text('')

    captured: dict[str, str] = {}

    def fake_run_path(path: str, run_name: str) -> None:
        captured['path'] = path
        captured['run_name'] = run_name
        captured['sys0'] = launcher.sys.path[0]

    monkeypatch.setattr(launcher, '_resolve_entry_file', lambda: entry_file)
    monkeypatch.setattr(launcher.runpy, 'run_path', fake_run_path)

    original = list(launcher.sys.path)
    try:
        launcher.main()
    finally:
        launcher.sys.path[:] = original

    assert captured['path'] == str(entry_file)
    assert captured['run_name'] == '__main__'
    assert captured['sys0'] == str(tmp_path)


def test_main_fallback_prepends_editable_root(monkeypatch, tmp_path: Path) -> None:
    called = {'main': False, 'sys0': ''}

    def fake_main() -> None:
        called['main'] = True
        called['sys0'] = launcher.sys.path[0]

    monkeypatch.setattr(launcher, '_resolve_entry_file', lambda: None)
    monkeypatch.setattr(launcher, '_editable_project_root', lambda: tmp_path)
    monkeypatch.setattr(
        launcher.importlib,
        'import_module',
        lambda _name: SimpleNamespace(main=fake_main),
    )

    original = list(launcher.sys.path)
    try:
        launcher.main()
    finally:
        launcher.sys.path[:] = original

    assert called['main'] is True
    assert called['sys0'] == str(tmp_path)
