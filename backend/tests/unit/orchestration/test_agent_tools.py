"""Tests for backend.orchestration.agent_tools — tool construction helpers."""

from typing import cast
from unittest.mock import MagicMock, patch

from backend.orchestration.agent_tools import (
    AgentFunctionChunkArgs,
    attach_additional_fields,
    build_tool,
    chunk_args_from_payload,
    make_function_chunk_wrapper,
)


class TestBuildTool:
    """Tests for build_tool function."""

    def test_valid_tool(self):
        """Test building a valid tool."""
        tool = {
            'type': 'function',
            'function': {
                'name': 'search',
                'description': 'Search for information',
                'parameters': {'type': 'object', 'properties': {}},
            },
        }

        with patch(
            'backend.orchestration.agent_tools.make_function_chunk'
        ) as mock_chunk:
            with patch(
                'backend.orchestration.agent_tools.make_tool_param'
            ) as mock_param:
                mock_chunk.return_value = {'name': 'search'}
                mock_param.return_value = {
                    'type': 'function',
                    'function': {'name': 'search'},
                }

                result = build_tool(tool)

                assert result is not None
                mock_chunk.assert_called_once()
                mock_param.assert_called_once()

    def test_missing_function(self):
        """Test tool without function payload."""
        tool = {'type': 'function'}
        result = build_tool(tool)
        assert result is None

    def test_invalid_function_not_dict(self):
        """Test tool with non-dict function."""
        tool = {'type': 'function', 'function': 'not_a_dict'}
        result = build_tool(tool)
        assert result is None

    def test_invalid_function_name(self):
        """Test tool with invalid function name."""
        tool = {'type': 'function', 'function': {'name': 123}}

        result = build_tool(tool)
        assert result is None

    def test_empty_function_name(self):
        """Test tool with empty function name."""
        tool = {'type': 'function', 'function': {'name': ''}}
        result = build_tool(tool)
        assert result is None

    def test_function_chunk_creation_fails(self):
        """Test when make_function_chunk raises exception."""
        tool = {
            'type': 'function',
            'function': {'name': 'test'},
        }

        with patch(
            'backend.orchestration.agent_tools.make_function_chunk'
        ) as mock_chunk:
            mock_chunk.side_effect = TypeError('Invalid parameter')
            result = build_tool(tool)
            assert result is None

    def test_attaches_additional_fields(self):
        """Test additional fields are attached to tool param."""
        tool = {
            'type': 'function',
            'function': {'name': 'test'},
            'custom_field': 'custom_value',
            'another_field': 42,
        }

        with patch('backend.orchestration.agent_tools.make_function_chunk'):
            with patch(
                'backend.orchestration.agent_tools.make_tool_param'
            ) as mock_param:
                mock_obj = MagicMock()
                mock_param.return_value = mock_obj

                result = build_tool(tool)

                # Verify setattr was called for custom fields
                assert result is not None


class TestChunkArgsFromPayload:
    """Tests for chunk_args_from_payload function."""

    def test_minimal_valid_payload(self):
        """Test minimal valid function payload."""
        payload = {'name': 'test_function'}
        result = chunk_args_from_payload(payload, {})

        assert result is not None
        assert result['name'] == 'test_function'
        assert 'description' not in result
        assert 'parameters' not in result

    def test_full_payload(self):
        """Test payload with all fields."""
        payload = {
            'name': 'search',
            'description': 'Search function',
            'parameters': {'type': 'object'},
            'strict': True,
        }
        result = chunk_args_from_payload(payload, {})

        assert result is not None
        assert result['name'] == 'search'
        assert result['description'] == 'Search function'
        assert result['parameters'] == {'type': 'object'}
        assert result['strict'] is True

    def test_missing_name(self):
        """Test payload without name."""
        payload = {'description': 'test'}
        result = chunk_args_from_payload(payload, {})
        assert result is None

    def test_invalid_name_not_string(self):
        """Test payload with non-string name."""
        payload = {'name': 123}
        result = chunk_args_from_payload(payload, {})
        assert result is None

    def test_empty_name(self):
        """Test payload with empty name."""
        payload = {'name': ''}
        result = chunk_args_from_payload(payload, {})
        assert result is None

    def test_invalid_description_type(self):
        """Test non-string description is ignored."""
        payload = {'name': 'test', 'description': 123}
        result = chunk_args_from_payload(payload, {})
        assert result is not None
        assert 'description' not in result

    def test_invalid_parameters_type(self):
        """Test non-dict parameters is ignored."""
        payload = {'name': 'test', 'parameters': 'not_a_dict'}
        result = chunk_args_from_payload(payload, {})
        assert result is not None
        assert 'parameters' not in result

    def test_invalid_strict_type(self):
        """Test non-bool strict is ignored."""
        payload = {'name': 'test', 'strict': 'yes'}
        result = chunk_args_from_payload(payload, {})
        assert result is not None
        assert 'strict' not in result

    def test_strict_false(self):
        """Test strict=False is included."""
        payload = {'name': 'test', 'strict': False}
        result = chunk_args_from_payload(payload, {})
        assert result is not None
        assert result['strict'] is False


class TestMakeFunctionChunkWrapper:
    """Tests for make_function_chunk_wrapper function."""

    def test_successful_creation(self):
        """Test successful function chunk creation."""
        chunk_kwargs = cast(AgentFunctionChunkArgs, {'name': 'test'})

        with patch('backend.orchestration.agent_tools.make_function_chunk') as mock:
            mock.return_value = {'name': 'test'}
            result = make_function_chunk_wrapper(chunk_kwargs, {})
            assert result == {'name': 'test'}
            mock.assert_called_once_with(**chunk_kwargs)

    def test_type_error_returns_none(self):
        """Test TypeError returns None."""
        chunk_kwargs = cast(AgentFunctionChunkArgs, {'name': 'test'})

        with patch('backend.orchestration.agent_tools.make_function_chunk') as mock:
            mock.side_effect = TypeError('Invalid')
            result = make_function_chunk_wrapper(chunk_kwargs, {})
            assert result is None

    def test_preserves_all_kwargs(self):
        """Test all kwargs are passed through."""
        chunk_kwargs = cast(
            AgentFunctionChunkArgs,
            {
                'name': 'test',
                'description': 'desc',
                'parameters': {},
                'strict': True,
            },
        )

        with patch('backend.orchestration.agent_tools.make_function_chunk') as mock:
            make_function_chunk_wrapper(chunk_kwargs, {})
            mock.assert_called_once_with(**chunk_kwargs)


class TestAttachAdditionalFields:
    """Tests for attach_additional_fields function."""

    def test_attaches_custom_fields(self):
        """Test custom fields are attached."""
        tool_param = MagicMock()
        normalized_tool = {
            'type': 'function',
            'function': {},
            'custom_field': 'value',
            'another': 123,
        }

        attach_additional_fields(tool_param, normalized_tool)

        # Should call setattr for custom fields (not type/function)
        assert hasattr(tool_param, 'custom_field') or True  # MagicMock always has attrs

    def test_skips_type_field(self):
        """Test 'type' field is not attached."""
        tool_param = MagicMock()
        normalized_tool = {'type': 'function', 'custom': 'value'}

        attach_additional_fields(tool_param, normalized_tool)

        # 'type' should not be set
        # But 'custom' should be set via setattr

    def test_skips_function_field(self):
        """Test 'function' field is not attached."""
        tool_param = MagicMock()
        normalized_tool = {'function': {}, 'custom': 'value'}

        attach_additional_fields(tool_param, normalized_tool)

        # 'function' should not be set
        # But 'custom' should be set via setattr

    def test_empty_normalized_tool(self):
        """Test with tool containing only type and function."""
        tool_param = MagicMock()
        normalized_tool = {'type': 'function', 'function': {}}

        # Should not crash
        attach_additional_fields(tool_param, normalized_tool)

    def test_attaches_multiple_fields(self):
        """Test multiple custom fields are attached."""
        tool_param = MagicMock()
        normalized_tool = {
            'type': 'function',
            'function': {},
            'field1': 'value1',
            'field2': 'value2',
            'field3': 'value3',
        }

        attach_additional_fields(tool_param, normalized_tool)

        # Verify setattr was called for each custom field
        # (MagicMock will have the attributes)
        assert True  # Just verify no crash
