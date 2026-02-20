# mypy: ignore-errors

import importlib
import os
import sys


def _sanitize_sys_path():
    backend_root = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.dirname(backend_root)
    if project_root in sys.path:
        sys.path.remove(project_root)
    sys.path.insert(0, project_root)

    _preload_pydantic_root_model()


def _preload_pydantic_root_model() -> None:
    try:
        pass  # type: ignore  # pylint: disable=unused-import
    except Exception:
        pass


_sanitize_sys_path()


import asyncio
import inspect
import pathlib
from collections.abc import Iterator

import pytest


@pytest.fixture
def event_loop():
    """Provide a fresh event loop for async tests without requiring pytest-asyncio."""
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        if not loop.is_closed():
            loop.close()


def pytest_pyfunc_call(pyfuncitem):
    """Execute coroutine tests by driving them with an event loop."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        loop = pyfuncitem.funcargs.get("event_loop")  # type: ignore[attr-defined]
        owns_loop = False
        if loop is None:
            loop = asyncio.new_event_loop()
            owns_loop = True

        try:
            asyncio.set_event_loop(loop)
            fixture_names = getattr(pyfuncitem, "_fixtureinfo").argnames
            test_kwargs = {name: pyfuncitem.funcargs[name] for name in fixture_names}
            loop.run_until_complete(pyfuncitem.obj(**test_kwargs))
        finally:
            asyncio.set_event_loop(None)
            if owns_loop and not loop.is_closed():
                loop.close()
        return True
    return None


def _has_pkg(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def pytest_configure(config):
    markers = ["windows", "optional", "heavy", "integration", "benchmark", "stress"]
    for m in markers:
        config.addinivalue_line("markers", f"{m}: mark test as {m}")


def _clear_forge_modules() -> None:
    """Aggressively clear any cached 'forge' and related modules before collecting a test.

    Some tests in this repository manipulate sys.modules at import time to stub
    out submodules (e.g., forge.events.observation). To prevent cross-module
    contamination during collection, clear any previously imported modules
    so each test module starts from a clean import state.
    """
    # Avoid clearing modules that register global side effects (e.g., Prometheus metrics)
    # which cannot be re-registered safely across repeated imports during collection.
    EXCLUDE_PREFIXES = ()
    TARGET_PACKAGES = (
        "forge",
        "integrations",
        "engines",
    )
    try:
        for name in list(sys.modules.keys()):
            if any(
                name == pkg or name.startswith(pkg + ".") for pkg in TARGET_PACKAGES
            ):
                if any(name == p or name.startswith(p + ".") for p in EXCLUDE_PREFIXES):
                    continue
                sys.modules.pop(name, None)
    except Exception:
        pass


def pytest_collectstart(collector):
    # Called before starting collection of a node (including test modules).
    # Reset forge imports to avoid sys.modules pollution from previously imported tests.
    _clear_forge_modules()


@pytest.fixture
def require_pkg(request):
    """Fixture to skip a test if a package is missing.

    Usage: def test_foo(require_pkg): require_pkg('reportlab')
    """

    def _require(name: str):
        if not _has_pkg(name):
            pytest.skip(f"skipping test, missing required package: {name}")

    return _require


def _is_benchmark_test(parts):
    """Check if test is a benchmark test based on path parts."""
    return "evaluation" in parts or "benchmarks" in parts or "benchmark" in parts


def _is_heavy_test(parts):
    """Check if test is a heavy test based on path parts."""
    return "third_party" in parts or "external" in parts


def _is_integration_test(parts):
    """Check if test is an integration test based on path parts."""
    return "tests" in parts and ("e2e" in parts or "integration" in parts)


def _add_markers_to_item(item, parts):
    """Add appropriate markers to test item based on path parts."""
    if _is_benchmark_test(parts):
        item.add_marker(pytest.mark.benchmark)
        item.add_marker(pytest.mark.heavy)

    if _is_heavy_test(parts):
        item.add_marker(pytest.mark.heavy)

    if _is_integration_test(parts):
        item.add_marker(pytest.mark.integration)


def pytest_collection_modifyitems(config, items):
    """Modify test items by adding markers and applying skips."""
    _apply_path_markers(items)
    context = _CollectionContext(
        is_windows=sys.platform.startswith("win"),
        run_tty_tests=os.environ.get("FORGE_RUN_TTY_TESTS", "0") == "1",
    )
    _apply_skip_markers(items, context)


def _apply_path_markers(items):
    for item in items:
        parts = {part.lower() for part in pathlib.Path(item.fspath).parts}
        _add_markers_to_item(item, parts)


class _CollectionContext:
    def __init__(self, is_windows: bool, run_tty_tests: bool):
        self.is_windows = is_windows
        self.run_tty_tests = run_tty_tests


def _apply_skip_markers(items, context: "_CollectionContext") -> None:
    for item in items:
        for reason in _skip_reasons(item, context):
            item.add_marker(pytest.mark.skip(reason=reason))


def _skip_reasons(item, context: "_CollectionContext") -> Iterator[str]:
    if "windows" in item.keywords and not context.is_windows:
        yield "windows-specific test (not running on non-windows host)"
    if "tty" in item.keywords and not context.run_tty_tests:
        yield "tty tests disabled; set FORGE_RUN_TTY_TESTS=1 to enable"
    # Runtime tests are local-only in this branch.
    if _is_runtime_test(item):
        test_runtime = os.environ.get("TEST_RUNTIME", "local").lower()
        if test_runtime != "local":
            yield "runtime tests skipped: only local runtime is supported in this branch"


def _is_runtime_test(item) -> bool:
    return "runtime" in pathlib.Path(item.fspath).parts


@pytest.fixture(autouse=True)
def use_repo_root_cwd(tmp_path, monkeypatch):
    """Autouse fixture that sets CWD to repository root for the test run.

    It uses the location of this conftest.py as a hint: repo root is the parent
    directory of the `Forge` package directory. This is intentionally
    conservative and only changes cwd for the duration of each test.
    """
    repo_root = pathlib.Path(__file__).resolve().parent
    try:
        assert repo_root.exists()
        monkeypatch.chdir(str(repo_root))
        yield
    finally:
        pass


# Removed LLM mocking and dummy environment fixtures.


# ---------------------------------------------------------------------------
# Runtime test helpers
# ---------------------------------------------------------------------------
# Removed runtime test helpers that relied on stale non-local runtime logic.

__all__ = [
    "event_loop",
    "pytest_pyfunc_call",
    "require_pkg",
    "use_repo_root_cwd",
]
