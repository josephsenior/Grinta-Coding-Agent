from pathlib import Path

import backend.conftest as backend_conftest


class _FakeItem:
    def __init__(self, *, keywords: set[str], path: str):
        self.keywords = {keyword: True for keyword in keywords}
        self.fspath = path
        self.markers: list[object] = []

    def add_marker(self, marker) -> None:
        self.markers.append(marker)


def test_pytest_collection_modifyitems_uses_app_run_tty_tests_env(monkeypatch):
    captured: dict[str, bool] = {}

    monkeypatch.setenv("APP_RUN_TTY_TESTS", "1")
    monkeypatch.setattr(backend_conftest, "_apply_path_markers", lambda items: None)

    def _capture_context(items, context):
        captured["run_tty_tests"] = context.run_tty_tests

    monkeypatch.setattr(backend_conftest, "_apply_skip_markers", _capture_context)

    backend_conftest.pytest_collection_modifyitems(None, [])

    assert captured == {"run_tty_tests": True}


def test_skip_reasons_mentions_app_run_tty_tests_env():
    item = _FakeItem(keywords={"tty"}, path=str(Path("backend/tests/unit/test_dummy.py")))
    context = backend_conftest._CollectionContext(is_windows=True, run_tty_tests=False)

    assert list(backend_conftest._skip_reasons(item, context)) == [
        "tty tests disabled; set APP_RUN_TTY_TESTS=1 to enable"
    ]