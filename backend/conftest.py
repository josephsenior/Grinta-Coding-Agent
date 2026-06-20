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


import pathlib  # noqa: E402
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402


def _has_pkg(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def pytest_configure(config):
    # Tests must not write session logs under logs/workspaces/ (no PROJECT_ROOT).
    os.environ['LOG_TO_FILE'] = 'false'
    markers = [
        'windows',
        'optional',
        'heavy',
        'integration',
        'stress',
        'asyncio',
    ]
    for m in markers:
        config.addinivalue_line('markers', f'{m}: mark test as {m}')


def _clear_app_modules() -> None:
    """Aggressively clear any cached 'app' and related modules before collecting a test.

    Some tests in this repository manipulate sys.modules at import time to stub
    out submodules (e.g., app.events.observation). To prevent cross-module
    contamination during collection, clear any previously imported modules
    so each test module starts from a clean import state.
    """
    # Avoid clearing modules that register global side effects (e.g., Prometheus metrics)
    # which cannot be re-registered safely across repeated imports during collection.
    EXCLUDE_PREFIXES = ()
    TARGET_PACKAGES = ('engine',)
    try:
        for name in list(sys.modules.keys()):
            if any(
                name == pkg or name.startswith(pkg + '.') for pkg in TARGET_PACKAGES
            ):
                if any(name == p or name.startswith(p + '.') for p in EXCLUDE_PREFIXES):
                    continue
                sys.modules.pop(name, None)
    except Exception:
        pass


def pytest_collectstart(collector):
    # Called before starting collection of a node (including test modules).
    # Reset app imports to avoid sys.modules pollution from previously imported tests.
    _clear_app_modules()


@pytest.fixture
def require_pkg(request):
    """Fixture to skip a test if a package is missing.

    Usage: def test_foo(require_pkg): require_pkg('reportlab')
    """

    def _require(name: str):
        if not _has_pkg(name):
            pytest.skip(f'skipping test, missing required package: {name}')

    return _require


def _is_benchmark_test(parts):
    """Check if test is a benchmark test based on path parts."""
    return 'evaluation' in parts or 'benchmarks' in parts or 'benchmark' in parts


def _is_heavy_test(parts):
    """Check if test is a heavy test based on path parts."""
    return 'third_party' in parts or 'external' in parts


def _is_integration_test(parts):
    """Check if test is an integration test based on path parts."""
    return 'tests' in parts and ('e2e' in parts or 'integration' in parts)


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
        is_windows=sys.platform.startswith('win'),
        run_tty_tests=os.environ.get('APP_RUN_TTY_TESTS', '0') == '1',
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


def _apply_skip_markers(items, context: '_CollectionContext') -> None:
    for item in items:
        for reason in _skip_reasons(item, context):
            item.add_marker(pytest.mark.skip(reason=reason))


def _skip_reasons(item, context: '_CollectionContext') -> Iterator[str]:
    if 'windows' in item.keywords and not context.is_windows:
        yield 'windows-specific test (not running on non-windows host)'
    if 'tty' in item.keywords and not context.run_tty_tests:
        yield 'tty tests disabled; set APP_RUN_TTY_TESTS=1 to enable'
    # Runtime tests are local-only in this branch.
    if _is_runtime_test(item):
        test_runtime = os.environ.get('TEST_RUNTIME', 'local').lower()
        if test_runtime != 'local':
            yield 'runtime tests skipped: only local runtime is supported in this branch'


def _is_runtime_test(item) -> bool:
    return 'runtime' in pathlib.Path(item.fspath).parts


@pytest.fixture(autouse=True)
def _disable_file_logging_during_tests(monkeypatch):
    """Keep pytest runs from creating logs/workspaces/*/sessions/* directories."""
    monkeypatch.setattr('backend.core.logging.logger.LOG_TO_FILE', False)


@pytest.fixture(autouse=True)
def use_repo_root_cwd(tmp_path, monkeypatch):
    """Autouse fixture that sets CWD to repository root for the test run.

    It uses the location of this conftest.py as a hint: repo root is the parent
    directory of the `backend` package directory. This is intentionally
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
    'require_pkg',
    'use_repo_root_cwd',
]
