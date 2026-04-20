"""Tests for editor-only shell write policy."""

from __future__ import annotations

import pytest

from backend.core.config.security_config import SecurityConfig
from backend.execution.editor_only_shell_policy import evaluate_editor_only_shell_block


def _cfg(**kwargs) -> SecurityConfig:
    base: dict = {'require_editor_for_shell_file_writes': True}
    base.update(kwargs)
    return SecurityConfig.model_validate(base)


@pytest.mark.parametrize(
    ('command',),
    [
        ('Set-Content -Path index.html -Value "<html>"',),
        ('Add-Content -Path foo.css -Value "x"',),
        ('Out-File -FilePath README.md -InputObject hi',),
        ('echo hello > out.txt',),
        ('printf x > notes.md',),
        ('ls | tee result.txt',),
        ('dd if=/dev/zero of=image.img bs=1 count=1',),
    ],
)
def test_blocks_obvious_shell_writes(command: str) -> None:
    msg = evaluate_editor_only_shell_block(
        command=command,
        security_config=_cfg(),
        workspace_root='/workspace',
    )
    assert msg is not None
    assert 'str_replace_editor' in msg


@pytest.mark.parametrize(
    ('command',),
    [
        ('Set-Content -Path build.log -Value "x"',),
        ('echo ok > trace.tmp',),
        ('python app.py > server.log 2>&1',),
        ('npm run build > output.log',),
    ],
)
def test_allows_log_and_tmp_redirections(command: str) -> None:
    assert (
        evaluate_editor_only_shell_block(
            command=command,
            security_config=_cfg(),
            workspace_root='/workspace',
        )
        is None
    )


def test_allows_toolchain_commands() -> None:
    assert (
        evaluate_editor_only_shell_block(
            command='git checkout -b feature',
            security_config=_cfg(),
            workspace_root='/workspace',
        )
        is None
    )
    assert (
        evaluate_editor_only_shell_block(
            command='cd pkg && npm install && npm run build',
            security_config=_cfg(),
            workspace_root='/workspace',
        )
        is None
    )


def test_disabled_via_config() -> None:
    assert (
        evaluate_editor_only_shell_block(
            command='Set-Content -Path x.html -Value z',
            security_config=_cfg(require_editor_for_shell_file_writes=False),
            workspace_root='/workspace',
        )
        is None
    )


def test_allows_powershell_to_temp() -> None:
    assert (
        evaluate_editor_only_shell_block(
            command="Set-Content -Path $env:TEMP\\scratch.txt -Value x",
            security_config=_cfg(),
            workspace_root='/workspace',
        )
        is None
    )


@pytest.mark.parametrize('truthy', ['1', 'true', 'yes', 'on'])
def test_env_override_allows_shell_writes(
    monkeypatch: pytest.MonkeyPatch, truthy: str
) -> None:
    # GRINTA_ALLOW_SHELL_WRITES lets callers opt back in to the permissive
    # behavior that OpenCode / Claude Code ship by default.
    monkeypatch.setenv('GRINTA_ALLOW_SHELL_WRITES', truthy)
    assert (
        evaluate_editor_only_shell_block(
            command='Set-Content -Path index.html -Value "<html>"',
            security_config=_cfg(),
            workspace_root='/workspace',
        )
        is None
    )


def test_env_override_off_preserves_block(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicit "off" must not accidentally flip-disable the block.
    monkeypatch.setenv('GRINTA_ALLOW_SHELL_WRITES', '0')
    msg = evaluate_editor_only_shell_block(
        command='Set-Content -Path index.html -Value "<html>"',
        security_config=_cfg(),
        workspace_root='/workspace',
    )
    assert msg is not None


def test_block_message_mentions_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('GRINTA_ALLOW_SHELL_WRITES', raising=False)
    msg = evaluate_editor_only_shell_block(
        command='Set-Content -Path index.html -Value z',
        security_config=_cfg(),
        workspace_root='/workspace',
    )
    assert msg is not None
    assert 'GRINTA_ALLOW_SHELL_WRITES' in msg
