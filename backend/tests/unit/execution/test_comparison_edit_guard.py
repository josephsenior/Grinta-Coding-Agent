"""Persistent-state comparison contract, exercised against real Git trees."""

import asyncio
import os
import subprocess
from types import SimpleNamespace

import pytest

from backend.execution.comparison_edit_guard import (
    ComparisonContractError,
    ComparisonEditGuard,
)


def git(repo, *args):
    return subprocess.check_output(
        [
            'git',
            '-c',
            'core.autocrlf=false',
            '-c',
            'user.name=Comparison Tests',
            '-c',
            'user.email=test@example.invalid',
            *args,
        ],
        cwd=repo,
    )


@pytest.fixture
def source(tmp_path):
    git(tmp_path, 'init')
    (tmp_path / 'a.py').write_bytes(b'x = 1\n')
    (tmp_path / 'old.py').write_bytes(b'old = True\n')
    (tmp_path / '.gitignore').write_bytes(b'build/\n')
    (tmp_path / 'binary.dat').write_bytes(b'\x00\x01')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'base')
    return tmp_path, ComparisonEditGuard(tmp_path)


def test_allowed_multifile_operations_and_ignored_build_products(source):
    repo, guard = source
    (repo / 'old.py').rename(repo / 'renamed.py')
    (repo / 'a.py').unlink()
    (repo / 'new.py').write_bytes(b'new = True\r\n')
    (repo / 'build').mkdir()
    (repo / 'build/output').write_bytes(b'\x00compiled')
    guard.check()
    (repo / 'renamed.py').write_bytes(b'old = False\n')
    guard.check()
    assert not git(repo, 'diff', '--cached').strip()


@pytest.mark.parametrize('kind', ['nul', 'non_utf8', 'delete_binary', 'case_collision'])
def test_unsupported_state_poisoning_cannot_be_recovered_by_later_action(source, kind):
    repo, guard = source
    if kind == 'delete_binary':
        (repo / 'binary.dat').unlink()
    elif kind == 'case_collision':
        if os.name == 'nt':
            pytest.skip(
                'requires a case-sensitive filesystem; covered by Linux diagnostic'
            )
        (repo / 'A.py').write_bytes(b'x = 2\n')
    else:
        (repo / 'a.py').write_bytes(b'\x00bad' if kind == 'nul' else b'\xffbad')
    with pytest.raises(ComparisonContractError):
        guard.check()
    (repo / 'a.py').write_bytes(b'x = 1\n')
    with pytest.raises(ComparisonContractError):
        guard.check()


@pytest.mark.skipif(os.name == 'nt', reason='Linux executable bits and symlinks')
@pytest.mark.parametrize('operation', ['chmod', 'symlink', 'new_executable'])
def test_unsupported_mode_and_type_changes(source, operation):
    repo, guard = source
    if operation == 'chmod':
        (repo / 'a.py').chmod(0o755)
    elif operation == 'symlink':
        (repo / 'link.py').symlink_to('a.py')
    else:
        (repo / 'new.sh').write_bytes(b'echo test\n')
        (repo / 'new.sh').chmod(0o755)
    with pytest.raises(ComparisonContractError):
        guard.check()


def test_final_patch_check_rejects_unsupported_changes(source):
    from evaluation.deepswe.run_grinta import _capture_patch

    repo, guard = source
    (repo / 'a.py').write_bytes(b'\0changed')
    with pytest.raises(ComparisonContractError):
        _capture_patch(repo, guard.base, comparison_edit_profile='agentless-ml-v1')
    assert 'GIT binary patch' in _capture_patch(repo, guard.base)


def test_real_dispatch_boundary_suppresses_invalid_feedback_and_stops_next_action(
    source,
):
    from backend.execution.io_mixins._aes_io_init_mixin import _AesIoInitMixin

    repo, guard = source

    class Harness(_AesIoInitMixin):
        def __init__(self):
            self.lock = asyncio.Lock()
            self._comparison_edit_guard = guard
            self.calls = 0

        async def scripted(self, action):
            self.calls += 1
            (repo / 'a.py').write_bytes(b'\0bad')
            return SimpleNamespace(content='this tool output must not reach the agent')

    harness = Harness()
    action = SimpleNamespace(action='scripted')
    with pytest.raises(ComparisonContractError):
        asyncio.run(harness.run_action(action))
    with pytest.raises(ComparisonContractError):
        asyncio.run(harness.run_action(action))
    assert harness.calls == 1


def test_delete_and_restore_within_one_action_is_intentionally_allowed(source):
    repo, guard = source
    (repo / 'a.py').unlink()
    (repo / 'a.py').write_bytes(b'x = 1\n')
    guard.check()


def test_new_path_cannot_replace_a_removed_file_with_a_directory(source):
    repo, guard = source
    (repo / 'old.py').unlink()
    (repo / 'old.py').mkdir()
    (repo / 'old.py/child.py').write_bytes(b'x = 1\n')
    with pytest.raises(ComparisonContractError, match='collides'):
        guard.check()


def test_unchanged_gitlink_is_allowed_but_pointer_change_is_rejected(source):
    repo, _ = source
    nested = repo / 'module'
    nested.mkdir()
    git(nested, 'init')
    (nested / 'file.txt').write_bytes(b'base\n')
    git(nested, 'add', '.')
    git(nested, 'commit', '-m', 'nested base')
    git(repo, 'add', 'module')
    git(repo, 'commit', '-m', 'gitlink')
    guard = ComparisonEditGuard(repo)
    guard.check()
    (repo / 'a.py').write_bytes(b'x = 2\n')
    guard.check()
    (nested / 'file.txt').write_bytes(b'changed\n')
    git(nested, 'add', '.')
    git(nested, 'commit', '-m', 'changed pointer')
    with pytest.raises(ComparisonContractError, match='submodule'):
        guard.check()
