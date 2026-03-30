import os
from pathlib import Path

from backend.gateway.routes.conversation import (
    _is_under_repo_playbooks,
    _playbook_load_parent_dir,
    _repo_playbooks_root,
)


def test_repo_playbooks_root_points_to_app_playbooks_dir() -> None:
    workspace_root = "/workspace/project"

    assert _repo_playbooks_root(workspace_root) == os.path.normpath(
        "/workspace/project/.app/playbooks"
    )


def test_is_under_repo_playbooks_matches_root_and_children() -> None:
    workspace_root = "/workspace/project"

    assert _is_under_repo_playbooks(workspace_root, "/workspace/project/.app/playbooks")
    assert _is_under_repo_playbooks(
        workspace_root,
        "/workspace/project/.app/playbooks/repo.md",
    )
    assert not _is_under_repo_playbooks(
        workspace_root,
        "/workspace/project/docs/repo.md",
    )


def test_playbook_load_parent_dir_uses_repo_playbooks_root_for_repo_playbooks() -> None:
    workspace_root = "/workspace/project"

    assert _playbook_load_parent_dir(
        workspace_root,
        "/workspace/project/.app/playbooks/subdir/repo.md",
    ) == Path("/workspace/project/.app/playbooks")


def test_playbook_load_parent_dir_uses_file_parent_for_non_repo_playbooks() -> None:
    workspace_root = "/workspace/project"

    assert _playbook_load_parent_dir(
        workspace_root,
        "/workspace/project/custom/playbooks/repo.md",
    ) == Path("/workspace/project/custom/playbooks")