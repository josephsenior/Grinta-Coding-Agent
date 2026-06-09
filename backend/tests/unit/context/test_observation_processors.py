"""Tests for backend.context.observation_processors."""

from __future__ import annotations

from types import SimpleNamespace

from backend.context.message_formatting import extract_first_text
from backend.context.observation_processors import (
    _get_observation_content,
    _handle_simple_observation,
    convert_observation_to_message,
)
from backend.context.pre_condensation_snapshot import save_snapshot
from backend.core.message import ImageContent, TextContent
from backend.ledger.observation import (
    BrowserScreenshotObservation,
    CmdOutputObservation,
    ErrorObservation,
    FileEditObservation,
    FileReadObservation,
    MCPObservation,
    UserRejectObservation,
)
from backend.ledger.observation.agent import (
    AgentCondensationObservation,
    AgentThinkObservation,
)

# ── _get_observation_content ─────────────────────────────────────────


class TestGetObservationContent:
    def test_content_attr(self):
        obs = SimpleNamespace(content='hello')
        assert _get_observation_content(obs) == 'hello'  # type: ignore[arg-type]

    def test_message_attr(self):
        obs = SimpleNamespace(message='msg')
        assert _get_observation_content(obs) == 'msg'  # type: ignore[arg-type]

    def test_fallback_str(self):
        obs = SimpleNamespace()
        result = _get_observation_content(obs)  # type: ignore[arg-type]
        assert isinstance(result, str)


# ── _handle_simple_observation ───────────────────────────────────────


class TestHandleSimpleObservation:
    def test_basic(self):
        obs = SimpleNamespace(content='output')
        msg = _handle_simple_observation(obs, None)  # type: ignore[arg-type]
        assert msg.role == 'user'
        assert msg.content[0].text == 'output'  # type: ignore[union-attr]

    def test_with_prefix_and_suffix(self):
        obs = SimpleNamespace(content='body')
        msg = _handle_simple_observation(obs, None, prefix='P:', suffix=':S')  # type: ignore[arg-type]
        assert msg.content[0].text == 'P:body:S'  # type: ignore[union-attr]

    def test_truncation(self):
        obs = SimpleNamespace(content='x' * 200)
        msg = _handle_simple_observation(obs, 50)  # type: ignore[arg-type]
        assert len(msg.content[0].text) < 200  # type: ignore[union-attr]


# ── convert_observation_to_message ───────────────────────────────────


class TestConvertObservation:
    def test_error_observation(self):
        obs = ErrorObservation(content='bad thing')
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert 'bad thing' in msg.content[0].text  # type: ignore[union-attr]
        assert '[ERROR' in msg.content[0].text  # type: ignore[union-attr]

    def test_user_reject_observation(self):
        obs = UserRejectObservation(content='no thanks')
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert 'no thanks' in msg.content[0].text  # type: ignore[union-attr]
        assert 'rejected' in msg.content[0].text.lower()  # type: ignore[union-attr]

    def test_file_read_observation(self):
        obs = FileReadObservation(content='file content', path='/tmp/x.py')
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert '[FILE_READ' in msg.content[0].text  # type: ignore[union-attr]
        assert 'file content' in msg.content[0].text  # type: ignore[union-attr]

    def test_file_edit_observation(self):
        obs = FileEditObservation(
            content='edited',
            path='/tmp/x.py',
            old_content='original',
            new_content='edited',
            prev_exist=True,
        )
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert msg.role == 'user'

    def test_mcp_observation(self):
        obs = MCPObservation(content='mcp result')
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert '[MCP_RESULT' in msg.content[0].text  # type: ignore[union-attr]
        assert 'mcp result' in msg.content[0].text  # type: ignore[union-attr]

    def test_tool_backed_think_observation_is_labeled_internal_tool_result(self):
        obs = AgentThinkObservation(content='Your thought has been logged.')
        obs.tool_result = {
            'ok': True,
            'retryable': False,
            'exit_code': None,
            'action': 'think',
            'observation': 'think',
        }

        msg = convert_observation_to_message(obs, max_message_chars=None)

        assert msg.role == 'user'
        text = msg.content[0].text  # type: ignore[union-attr]
        assert text.startswith('Internal tool observation, not a user request.')
        payload = text.split('\n', 1)[1]
        assert '"action": "think"' in payload
        assert '"observation": "think"' in payload

    def test_cmd_output_observation(self):
        obs = CmdOutputObservation(
            content='output text',
            command='ls',
            command_id=1,
        )
        msg = convert_observation_to_message(obs, max_message_chars=None)
        assert msg.role == 'user'

    def test_browser_screenshot_observation_injects_image_when_vision_active(self):
        obs = BrowserScreenshotObservation(
            content='Screenshot saved to: /tmp/a.jpg (4 bytes)',
            image_path='/tmp/a.jpg',
            image_b64='QUJDQw==',
            image_mime='image/jpeg',
        )
        msg = convert_observation_to_message(
            obs, max_message_chars=None, vision_is_active=True
        )
        assert msg.vision_enabled is True
        assert any(isinstance(c, ImageContent) for c in msg.content)

    def test_browser_screenshot_observation_text_only_when_vision_off(self):
        obs = BrowserScreenshotObservation(
            content='Screenshot saved to: /tmp/a.jpg (4 bytes)',
            image_path='/tmp/a.jpg',
            image_b64='QUJDQw==',
        )
        msg = convert_observation_to_message(
            obs, max_message_chars=None, vision_is_active=False
        )
        assert all(isinstance(c, TextContent) for c in msg.content)

    def test_condensation_observation_restores_scratchpad_and_working_memory(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            'backend.context.observation_processors._load_scratchpad_snapshot',
            lambda: '\nSCRATCHPAD\n',
        )
        monkeypatch.setattr(
            'backend.context.observation_processors._load_working_memory_snapshot',
            lambda: '\nWORKING_MEMORY\n',
        )
        obs = AgentCondensationObservation(content='summary')

        msg = convert_observation_to_message(obs, max_message_chars=None)

        content = msg.content[0]
        assert isinstance(content, TextContent)
        text = content.text
        assert 'summary' in text
        assert 'SCRATCHPAD' in text
        assert 'WORKING_MEMORY' in text

    def test_condensation_observation_restores_snapshot_once(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            'backend.core.workspace_resolution.workspace_agent_state_dir',
            lambda project_root=None: tmp_path,
        )
        save_snapshot(
            {
                'events_condensed': 7,
                'files_touched': {'src/main.py': {'action': 'edit'}},
                'recent_errors': ['failure'],
                'decisions': [],
                'recent_commands': [],
                'attempted_approaches': [],
            }
        )
        obs = AgentCondensationObservation(content='summary')

        first = convert_observation_to_message(obs, max_message_chars=None)
        first_text = extract_first_text(first)
        assert first_text is not None
        assert '<RESTORED_CONTEXT>' in first_text
        assert 'src/main.py' in first_text
        assert 'failure' in first_text

        second = convert_observation_to_message(obs, max_message_chars=None)
        second_text = extract_first_text(second)
        assert second_text is not None
        assert '<RESTORED_CONTEXT>' in second_text
        assert 'src/main.py' in second_text
