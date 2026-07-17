"""Integration tests for settings, safety, file store, and task validation components."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from backend.core.constants import LLM_API_KEY_SETTINGS_PLACEHOLDER
from backend.core.os_capabilities import OS_CAPS
from backend.ledger.action import ActionSecurityRisk
from backend.ledger.action.files import FileEditAction
from backend.orchestration.state.state import State
from backend.persistence.data_models.settings import Settings
from backend.persistence.file_store.local_file_store import LocalFileStore
from backend.persistence.settings.file_settings_store import FileSettingsStore
from backend.security.command_analyzer import CommandAnalyzer
from backend.validation.task_validator import (
    CompositeValidator,
    DiffValidator,
    FileExistsValidator,
    Task,
)


@pytest.fixture()
def temp_dir(tmp_path: Path) -> Path:
    """Fixture to provide a clean temporary directory."""
    return tmp_path


# ── Settings & FileStore Integration ──────────────────────────────────────


@pytest.mark.integration
async def test_settings_filestore_integration(temp_dir: Path) -> None:
    """Test full integration of Settings model, FileSettingsStore, and LocalFileStore."""
    # 1. Initialize local file store
    store_dir = temp_dir / 'store'
    store_dir.mkdir()
    file_store = LocalFileStore(str(store_dir))

    # 2. Create settings store
    settings_store = FileSettingsStore(file_store=file_store, path='settings.json')

    # 3. Create settings and save
    settings = Settings(
        llm_model='openai/gpt-4.0',
        llm_api_key=SecretStr('my-api-key'),
        llm_base_url='https://api.openai.com/v1',
        mcp_config=None,
    )

    # Mock persist_llm_api_key_to_dotenv since we don't want to modify local .env files
    with (
        patch(
            'backend.persistence.settings.file_settings_store.persist_llm_api_key_to_dotenv'
        ) as mock_persist,
        patch(
            'backend.persistence.settings.file_settings_store.get_app_settings_root',
            return_value=str(store_dir),
        ),
    ):
        await settings_store.store(settings)
        mock_persist.assert_called_once()

    # 4. Verify serialized file contents
    assert (store_dir / 'settings.json').exists()
    file_content = (store_dir / 'settings.json').read_text(encoding='utf-8')
    data = json.loads(file_content)
    assert data['llm_model'] == 'openai/gpt-4.0'
    assert data['llm_api_key'] == LLM_API_KEY_SETTINGS_PLACEHOLDER
    assert data['llm_base_url'] == 'https://api.openai.com/v1'

    # 5. Reload settings
    reloaded = await settings_store.load()
    assert reloaded is not None
    assert reloaded.llm_model == 'openai/gpt-4.0'
    assert reloaded.llm_base_url == 'https://api.openai.com/v1'


# ── Safety Config & Command Analysis Integration ──────────────────────────


@pytest.mark.integration
def test_safety_command_analyzer_integration() -> None:
    """Test CommandAnalyzer integration with SafetyConfig rules."""
    analyzer = CommandAnalyzer()

    # 1. Analyze safe command
    res1 = analyzer.analyze_command('git status')
    assert res1.risk_level == ActionSecurityRisk.LOW

    # 2. Analyze medium risk command
    res2 = analyzer.analyze_command('npm install lodash')
    assert res2.risk_level == ActionSecurityRisk.MEDIUM
    assert res2.risk_category.value == 'medium'

    # 3. Analyze high risk command
    res3 = analyzer.analyze_command('rm -rf /usr/bin')
    assert res3.risk_level == ActionSecurityRisk.HIGH
    assert res3.risk_category.value == 'critical'

    # 4. Analyze obfuscated command
    res4 = analyzer.analyze_command("echo 'cm0gLXJmIC8=' | base64 --decode | sh")
    assert res4.risk_level == ActionSecurityRisk.HIGH
    assert res4.is_encoded is True


# ── Path Normalization & FileStore Integration ────────────────────────────


@pytest.mark.integration
def test_path_normalization_filestore_integration(temp_dir: Path) -> None:
    """Test writing and reading files through LocalFileStore using normalized paths."""
    from backend.utils.path_normalize import to_native_path

    file_store = LocalFileStore(str(temp_dir))

    # We write a file using a path that requires normalization
    if OS_CAPS.is_windows:
        flaky_path = 'subdir\\subfolder\\.\\file.txt'
    else:
        flaky_path = 'subdir/subfolder/./file.txt'

    normalized = to_native_path(flaky_path)

    # Write via FileStore
    file_store.write(normalized, 'integrated content')

    # Read back and verify
    assert file_store.read(normalized) == 'integrated content'
    assert (temp_dir / 'subdir' / 'subfolder' / 'file.txt').exists()


# ── Task Validator Composite Integration ──────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_composite_validator_integration() -> None:
    """Test CompositeValidator integrating DiffValidator and FileExistsValidator."""
    diff_val = DiffValidator()
    file_val = FileExistsValidator(expected_files=['output.json'])

    composite = CompositeValidator(
        validators=[diff_val, file_val],
        min_confidence=0.75,
        require_all_pass=True,
    )

    # 1. Scenario: Fail (no changes made)
    task = Task(description='Modify settings and produce output.json')
    state = State()  # Empty history

    with (
        patch.object(diff_val, '_get_diff_output', return_value=''),
        patch.object(diff_val, '_changed_paths_in_history', return_value=[]),
    ):
        result = await composite.validate_completion(task, state)
        assert result.passed is False
        assert len(result.missing_items) > 0

    # 2. Scenario: Pass (both validators satisfy criteria)
    # File edit event in history satisfies FileExistsValidator
    mock_event = MagicMock(spec=FileEditAction)
    mock_event.path = 'output.json'
    state.history = [mock_event]

    # Git diff content satisfies DiffValidator
    git_diff = '+new line of config\n'

    with (
        patch.object(diff_val, '_get_diff_output', return_value=git_diff),
        patch.object(
            diff_val, '_changed_paths_in_history', return_value=['output.json']
        ),
    ):
        result2 = await composite.validate_completion(task, state)
        assert result2.passed is True
        assert result2.confidence >= 0.75
