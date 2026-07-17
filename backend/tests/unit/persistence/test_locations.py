"""Tests for backend.persistence.locations — conversation path helpers."""

from backend.persistence.locations import (
    get_conversation_agent_state_filename,
    get_conversation_checkpoints_dir,
    get_conversation_dir,
    get_conversation_event_filename,
    get_conversation_events_dir,
    get_conversation_init_data_filename,
    get_conversation_llm_registry_filename,
    get_conversation_metadata_filename,
    get_conversation_stats_filename,
)


class TestGetConversationDir:
    """Tests for get_conversation_dir function."""

    def test_without_user_id(self):
        """Test conversation dir without user_id."""
        result = get_conversation_dir('session123')
        assert result == 'sessions/session123/'

    def test_with_user_id(self):
        """Test conversation dir with user_id."""
        result = get_conversation_dir('session123', user_id='user456')
        assert result == 'users/user456/conversations/session123/'

    def test_different_session_ids(self):
        """Test different session IDs produce different paths."""
        result1 = get_conversation_dir('session1')
        result2 = get_conversation_dir('session2')
        assert result1 != result2
        assert 'session1' in result1
        assert 'session2' in result2

    def test_ends_with_slash(self):
        """Test result ends with slash."""
        result = get_conversation_dir('test')
        assert result.endswith('/')


class TestGetConversationEventsDir:
    """Tests for get_conversation_events_dir function."""

    def test_without_user_id(self):
        """Test events dir without user_id."""
        result = get_conversation_events_dir('session123')
        assert result == 'sessions/session123/events/'

    def test_with_user_id(self):
        """Test events dir with user_id."""
        result = get_conversation_events_dir('session123', user_id='user456')
        assert result == 'users/user456/conversations/session123/events/'

    def test_ends_with_events_slash(self):
        """Test result ends with events/."""
        result = get_conversation_events_dir('test')
        assert result.endswith('events/')


class TestGetConversationEventFilename:
    """Tests for get_conversation_event_filename function."""

    def test_without_user_id(self):
        """Test event filename without user_id."""
        result = get_conversation_event_filename('session123', id=5)
        assert result == 'sessions/session123/events/5.json'

    def test_with_user_id(self):
        """Test event filename with user_id."""
        result = get_conversation_event_filename('session123', id=10, user_id='user456')
        assert result == 'users/user456/conversations/session123/events/10.json'

    def test_different_event_ids(self):
        """Test different event IDs."""
        result1 = get_conversation_event_filename('session', id=1)
        result2 = get_conversation_event_filename('session', id=2)
        assert '1.json' in result1
        assert '2.json' in result2

    def test_zero_event_id(self):
        """Test event ID of zero."""
        result = get_conversation_event_filename('session', id=0)
        assert result.endswith('0.json')


class TestGetConversationMetadataFilename:
    """Tests for get_conversation_metadata_filename function."""

    def test_without_user_id(self):
        """Test metadata filename without user_id."""
        result = get_conversation_metadata_filename('session123')
        assert result == 'sessions/session123/metadata.json'

    def test_with_user_id(self):
        """Test metadata filename with user_id."""
        result = get_conversation_metadata_filename('session123', user_id='user456')
        assert result == 'users/user456/conversations/session123/metadata.json'

    def test_ends_with_metadata_json(self):
        """Test result ends with metadata.json."""
        result = get_conversation_metadata_filename('test')
        assert result.endswith('metadata.json')


class TestGetConversationInitDataFilename:
    """Tests for get_conversation_init_data_filename function."""

    def test_without_user_id(self):
        """Test init data filename without user_id."""
        result = get_conversation_init_data_filename('session123')
        assert result == 'sessions/session123/init.json'

    def test_with_user_id(self):
        """Test init data filename with user_id."""
        result = get_conversation_init_data_filename('session123', user_id='user456')
        assert result == 'users/user456/conversations/session123/init.json'

    def test_ends_with_init_json(self):
        """Test result ends with init.json."""
        result = get_conversation_init_data_filename('test')
        assert result.endswith('init.json')


class TestGetConversationAgentStateFilename:
    """Tests for get_conversation_agent_state_filename function."""

    def test_without_user_id(self):
        """Test agent state filename without user_id."""
        result = get_conversation_agent_state_filename('session123')
        assert result == 'sessions/session123/agent_state.json'

    def test_with_user_id(self):
        """Test agent state filename with user_id."""
        result = get_conversation_agent_state_filename('session123', user_id='user456')
        assert result == 'users/user456/conversations/session123/agent_state.json'

    def test_ends_with_json(self):
        """Test result ends with .json."""
        result = get_conversation_agent_state_filename('test')
        assert result.endswith('agent_state.json')


class TestGetConversationLlmRegistryFilename:
    """Tests for get_conversation_llm_registry_filename function."""

    def test_without_user_id(self):
        """Test LLM registry filename without user_id."""
        result = get_conversation_llm_registry_filename('session123')
        assert result == 'sessions/session123/llm_registry.json'

    def test_with_user_id(self):
        """Test LLM registry filename with user_id."""
        result = get_conversation_llm_registry_filename('session123', user_id='user456')
        assert result == 'users/user456/conversations/session123/llm_registry.json'

    def test_ends_with_llm_registry_json(self):
        """Test result ends with llm_registry.json."""
        result = get_conversation_llm_registry_filename('test')
        assert result.endswith('llm_registry.json')


class TestGetConversationStatsFilename:
    """Tests for get_conversation_stats_filename function."""

    def test_without_user_id(self):
        """Test stats filename without user_id."""
        result = get_conversation_stats_filename('session123')
        assert result == 'sessions/session123/conversation_stats.pkl'

    def test_with_user_id(self):
        """Test stats filename with user_id."""
        result = get_conversation_stats_filename('session123', user_id='user456')
        assert result == 'users/user456/conversations/session123/conversation_stats.pkl'

    def test_ends_with_pkl(self):
        """Test result ends with .pkl."""
        result = get_conversation_stats_filename('test')
        assert result.endswith('conversation_stats.pkl')


class TestGetConversationCheckpointsDir:
    """Tests for get_conversation_checkpoints_dir function."""

    def test_without_user_id(self):
        """Test checkpoints dir without user_id."""
        result = get_conversation_checkpoints_dir('session123')
        assert result == 'sessions/session123/checkpoints/'

    def test_with_user_id(self):
        """Test checkpoints dir with user_id."""
        result = get_conversation_checkpoints_dir('session123', user_id='user456')
        assert result == 'users/user456/conversations/session123/checkpoints/'

    def test_ends_with_checkpoints_slash(self):
        """Test result ends with checkpoints/."""
        result = get_conversation_checkpoints_dir('test')
        assert result.endswith('checkpoints/')


class TestPathConsistency:
    """Tests for consistency across path functions."""

    def test_all_paths_use_same_base(self):
        """Test all path functions use same conversation_dir base."""
        sid = 'test_session'
        user_id = 'test_user'

        conv_dir = get_conversation_dir(sid, user_id)
        events_dir = get_conversation_events_dir(sid, user_id)
        metadata = get_conversation_metadata_filename(sid, user_id)
        init_data = get_conversation_init_data_filename(sid, user_id)
        agent_state = get_conversation_agent_state_filename(sid, user_id)

        # All should start with the same conversation dir
        assert events_dir.startswith(conv_dir)
        assert metadata.startswith(conv_dir)
        assert init_data.startswith(conv_dir)
        assert agent_state.startswith(conv_dir)

    def test_user_paths_vs_global_paths(self):
        """Test user-specific paths differ from global paths."""
        sid = 'session'

        global_dir = get_conversation_dir(sid)
        user_dir = get_conversation_dir(sid, user_id='user123')

        assert global_dir != user_dir
        assert 'users/' in user_dir
        assert 'users/' not in global_dir

    def test_event_filename_in_events_dir(self):
        """Test event filename is within events directory."""
        sid = 'session'
        events_dir = get_conversation_events_dir(sid)
        event_file = get_conversation_event_filename(sid, id=1)

        assert event_file.startswith(events_dir)


class TestLocationsExtendedCoverage:
    """Targeted coverage tests for locations storage, migrations, and local_data_root normalizations."""

    def test_maybe_migrate_legacy_project_storage_success(self, tmp_path):
        from backend.persistence.locations import _maybe_migrate_legacy_project_storage

        workspace = tmp_path / 'workspace'
        legacy_dir = workspace / '.grinta' / 'storage'
        legacy_dir.mkdir(parents=True)
        (legacy_dir / 'data.txt').write_text('legacy data')

        dest_storage = tmp_path / 'dest' / 'storage'

        _maybe_migrate_legacy_project_storage(workspace, dest_storage)

        # Verify moved successfully
        assert dest_storage.exists()
        assert (dest_storage / 'data.txt').read_text() == 'legacy data'
        assert not legacy_dir.exists()

    def test_maybe_migrate_legacy_project_storage_aborted(self, tmp_path):
        from backend.persistence.locations import _maybe_migrate_legacy_project_storage

        workspace = tmp_path / 'workspace'
        legacy_dir = workspace / '.grinta' / 'storage'
        legacy_dir.mkdir(parents=True)

        dest_storage = tmp_path / 'dest' / 'storage'
        dest_storage.mkdir(parents=True)  # Already exists!

        _maybe_migrate_legacy_project_storage(workspace, dest_storage)
        # Should not delete legacy if dest exists
        assert legacy_dir.exists()

    def test_maybe_migrate_legacy_project_storage_oserror(self, tmp_path):
        from unittest.mock import patch

        from backend.persistence.locations import _maybe_migrate_legacy_project_storage

        workspace = tmp_path / 'workspace'
        legacy_dir = workspace / '.grinta' / 'storage'
        legacy_dir.mkdir(parents=True)

        dest_storage = tmp_path / 'dest' / 'storage'

        with patch('shutil.move', side_effect=OSError('Permission denied')):
            _maybe_migrate_legacy_project_storage(workspace, dest_storage)
            # Should survive log warning and not raise exception
            assert legacy_dir.exists()

    def test_maybe_migrate_legacy_downloads_success(self, tmp_path):
        from backend.persistence.locations import _maybe_migrate_legacy_downloads

        workspace = tmp_path / 'workspace'
        legacy_dir = workspace / '.grinta' / 'downloads'
        legacy_dir.mkdir(parents=True)
        (legacy_dir / 'dl.txt').write_text('downloaded')

        dest_downloads = tmp_path / 'dest' / 'downloads'

        _maybe_migrate_legacy_downloads(workspace, dest_downloads)

        assert dest_downloads.exists()
        assert (dest_downloads / 'dl.txt').read_text() == 'downloaded'

    def test_maybe_migrate_legacy_downloads_oserror(self, tmp_path):
        from unittest.mock import patch

        from backend.persistence.locations import _maybe_migrate_legacy_downloads

        workspace = tmp_path / 'workspace'
        legacy_dir = workspace / '.grinta' / 'downloads'
        legacy_dir.mkdir(parents=True)

        dest_downloads = tmp_path / 'dest' / 'downloads'

        with patch('shutil.move', side_effect=OSError('Permission denied')):
            _maybe_migrate_legacy_downloads(workspace, dest_downloads)
            assert legacy_dir.exists()

    def test_get_project_local_data_root(self, tmp_path):
        from backend.persistence.locations import get_project_local_data_root

        # Resolve grinta root under ~/.grinta/workspaces/<hash>/storage
        root = get_project_local_data_root(tmp_path)
        assert 'workspaces' in root
        assert 'storage' in root

    def test_get_workspace_downloads_dir(self, tmp_path):
        from pathlib import Path

        from backend.persistence.locations import get_workspace_downloads_dir

        dl_dir = get_workspace_downloads_dir(tmp_path)
        assert 'workspaces' in dl_dir
        assert 'downloads' in dl_dir
        assert Path(dl_dir).exists()

    def test_config_str(self):
        from unittest.mock import MagicMock

        from backend.persistence.locations import _config_str

        cfg = MagicMock()
        cfg.local_data_root = '   /path/to/data   '
        assert _config_str(cfg, 'local_data_root') == '/path/to/data'

        # Non-string config returns empty string
        cfg.local_data_root = 123
        assert _config_str(cfg, 'local_data_root') == ''

    def test_is_same_or_subpath(self, tmp_path):
        from pathlib import Path

        from backend.persistence.locations import _is_same_or_subpath

        parent = tmp_path / 'parent'
        child = parent / 'child'
        unrelated = tmp_path / 'other'

        parent.mkdir()
        child.mkdir()
        unrelated.mkdir()

        assert _is_same_or_subpath(parent, parent) is True
        assert _is_same_or_subpath(child, parent) is True
        assert _is_same_or_subpath(unrelated, parent) is False

        # OSError/ValueError handling
        from unittest.mock import patch

        with patch.object(Path, 'resolve', side_effect=ValueError('invalid path')):
            assert _is_same_or_subpath(child, parent) is False

    def test_get_local_data_root_normalization(self, tmp_path):
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from backend.persistence.locations import get_local_data_root

        # Configuration mock
        cfg = MagicMock()
        cfg.local_data_root = ''
        cfg.project_root = str(tmp_path)

        # When raw is empty, fallback to default_local_data_root
        root = get_local_data_root(cfg)
        assert 'workspaces' in root
        assert 'storage' in root

        # When local_data_root points to unrelated dir outside the workspace (non-subpath of tmp_path)
        outside_path = Path('/some/unrelated/directory/outside/workspace').resolve()
        cfg.local_data_root = str(outside_path)
        root2 = get_local_data_root(cfg)
        # Should be resolved to the outside directory itself
        assert root2 == str(outside_path)

        # When CWD matches reserved user app data dir
        actual_cwd = Path.cwd().resolve()
        with patch(
            'backend.persistence.locations._current_working_directory',
            return_value=actual_cwd,
        ):
            with patch(
                'backend.core.workspace_resolution.is_reserved_user_app_data_dir',
                return_value=True,
            ):
                cfg.local_data_root = './local_data'
                cfg.project_root = None
                root3 = get_local_data_root(cfg)
                assert root3 == str((actual_cwd / 'local_data').resolve())

        # When resolve_cli_workspace_directory is None and CWD is not reserved
        with patch(
            'backend.persistence.locations._current_working_directory',
            return_value=actual_cwd,
        ):
            with patch(
                'backend.core.workspace_resolution.is_reserved_user_app_data_dir',
                return_value=False,
            ):
                cfg.local_data_root = './sessions'
                cfg.project_root = None
                root4 = get_local_data_root(cfg)
                # It should redirect sessions relative to CWD to the CWD workspace-keyed storage
                assert 'workspaces' in root4
                assert 'storage' in root4

    def test_get_active_local_data_root(self):
        from unittest.mock import patch

        from backend.persistence.locations import get_active_local_data_root

        # Normal active load
        root = get_active_local_data_root()
        assert root is not None

        # Handle exceptions gracefully and return default local data root
        with patch(
            'backend.core.config.load_app_config',
            side_effect=Exception('Failed to load'),
        ):
            root_fallback = get_active_local_data_root()
            assert 'grinta' in root_fallback
