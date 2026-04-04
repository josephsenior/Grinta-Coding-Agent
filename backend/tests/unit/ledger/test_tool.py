"""Tests for backend.ledger.tool — tool call metadata utilities."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.ledger.tool import ToolCallMetadata, build_tool_call_metadata


def create_mock_response(response_id='chatcmpl-123', model='gpt-4'):
    """Create a properly configured mock response object."""
    mock = MagicMock()
    mock.id = response_id
    mock.model = model
    mock.choices = []
    return mock


# ── build_tool_call_metadata function ──────────────────────────────────


class TestBuildToolCallMetadata:
    """Test build_tool_call_metadata helper function."""

    def test_creates_metadata_with_all_fields(self):
        """Test creates ToolCallMetadata with all required fields."""
        response = create_mock_response('chatcmpl-123', 'gpt-4')

        metadata = build_tool_call_metadata(
            function_name='test_function',
            tool_call_id='call_abc',
            response_obj=response,
            total_calls_in_response=2,
        )

        assert isinstance(metadata, ToolCallMetadata)
        assert metadata.function_name == 'test_function'
        assert metadata.tool_call_id == 'call_abc'
        assert metadata.total_calls_in_response == 2

    def test_captures_model_response_lite(self):
        """Test captures lightweight model response representation."""
        response = create_mock_response('chatcmpl-456', 'gpt-3.5-turbo')

        metadata = build_tool_call_metadata(
            function_name='my_func',
            tool_call_id='call_xyz',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata.model_response is not None
        assert isinstance(metadata.model_response, dict)

    def test_stores_raw_response_privately(self):
        """Test stores raw SDK response in private attribute."""
        response = create_mock_response('chatcmpl-789')

        metadata = build_tool_call_metadata(
            function_name='func',
            tool_call_id='call_123',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata._raw_response is response


# ── ToolCallMetadata class ─────────────────────────────────────────────


class TestToolCallMetadata:
    """Test ToolCallMetadata data model."""

    def test_from_sdk_creates_instance(self):
        """Test from_sdk classmethod creates instance."""
        response = create_mock_response('chatcmpl-111', 'gpt-4')

        metadata = ToolCallMetadata.from_sdk(
            function_name='test',
            tool_call_id='call_aaa',
            response_obj=response,
            total_calls_in_response=3,
        )

        assert isinstance(metadata, ToolCallMetadata)

    def test_contains_function_name(self):
        """Test metadata contains function name."""
        response = create_mock_response()
        metadata = ToolCallMetadata.from_sdk(
            function_name='execute_code',
            tool_call_id='call_001',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata.function_name == 'execute_code'

    def test_contains_tool_call_id(self):
        """Test metadata contains tool call ID."""
        response = create_mock_response()
        metadata = ToolCallMetadata.from_sdk(
            function_name='read_file',
            tool_call_id='call_unique_123',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata.tool_call_id == 'call_unique_123'

    def test_contains_total_calls_count(self):
        """Test metadata contains total calls in response."""
        response = create_mock_response()
        metadata = ToolCallMetadata.from_sdk(
            function_name='func',
            tool_call_id='call_x',
            response_obj=response,
            total_calls_in_response=5,
        )

        assert metadata.total_calls_in_response == 5

    def test_model_response_is_dict(self):
        """Test model_response is serialized as dict."""
        response = create_mock_response('chatcmpl-222')

        metadata = ToolCallMetadata.from_sdk(
            function_name='func',
            tool_call_id='call_y',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert isinstance(metadata.model_response, dict)

    def test_raw_response_not_in_public_fields(self):
        """Test _raw_response is private and not serialized."""
        response = create_mock_response()
        metadata = ToolCallMetadata.from_sdk(
            function_name='func',
            tool_call_id='call_z',
            response_obj=response,
            total_calls_in_response=1,
        )

        dumped = metadata.model_dump()
        assert '_raw_response' not in dumped

    def test_can_serialize_to_dict(self):
        """Test can serialize metadata to dictionary."""
        response = create_mock_response('chatcmpl-333')

        metadata = ToolCallMetadata.from_sdk(
            function_name='my_function',
            tool_call_id='call_serialize',
            response_obj=response,
            total_calls_in_response=2,
        )

        dumped = metadata.model_dump()
        assert dumped['function_name'] == 'my_function'
        assert dumped['tool_call_id'] == 'call_serialize'
        assert dumped['total_calls_in_response'] == 2

    def test_preserves_original_response_object(self):
        """Test preserves reference to original SDK response."""
        response = create_mock_response()
        response.custom_field = 'test_value'

        metadata = ToolCallMetadata.from_sdk(
            function_name='func',
            tool_call_id='call_preserve',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata._raw_response.custom_field == 'test_value'

    def test_multiple_instances_have_independent_raw_responses(self):
        """Test multiple instances maintain independent raw responses."""
        response1 = create_mock_response('resp1')
        response2 = create_mock_response('resp2')

        metadata1 = ToolCallMetadata.from_sdk(
            function_name='func1',
            tool_call_id='call1',
            response_obj=response1,
            total_calls_in_response=1,
        )
        metadata2 = ToolCallMetadata.from_sdk(
            function_name='func2',
            tool_call_id='call2',
            response_obj=response2,
            total_calls_in_response=1,
        )

        assert metadata1._raw_response.id == 'resp1'
        assert metadata2._raw_response.id == 'resp2'


# ── build_tool_call_metadata function ──────────────────────────────────


class TestBuildToolCallMetadataHelper:
    """Test build_tool_call_metadata helper function."""

    def test_creates_metadata_with_all_fields(self):
        """Test creates ToolCallMetadata with all required fields."""
        response = create_mock_response('chatcmpl-123', 'gpt-4')
        response.choices = []

        metadata = build_tool_call_metadata(
            function_name='test_function',
            tool_call_id='call_abc',
            response_obj=response,
            total_calls_in_response=2,
        )

        assert isinstance(metadata, ToolCallMetadata)
        assert metadata.function_name == 'test_function'
        assert metadata.tool_call_id == 'call_abc'
        assert metadata.total_calls_in_response == 2

    def test_captures_model_response_lite(self):
        """Test captures lightweight model response representation."""
        response = create_mock_response('chatcmpl-456', 'gpt-3.5-turbo')

        metadata = build_tool_call_metadata(
            function_name='my_func',
            tool_call_id='call_xyz',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata.model_response is not None
        assert isinstance(metadata.model_response, dict)

    def test_stores_raw_response_privately(self):
        """Test stores raw SDK response in private attribute."""
        response = create_mock_response('chatcmpl-789')

        metadata = build_tool_call_metadata(
            function_name='func',
            tool_call_id='call_123',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata._raw_response is response


# ── ToolCallMetadata class ─────────────────────────────────────────────


class TestToolCallMetadataModel:
    """Test ToolCallMetadata data model."""

    def test_from_sdk_creates_instance(self):
        """Test from_sdk classmethod creates instance."""
        response = create_mock_response('chatcmpl-111', 'gpt-4')

        metadata = ToolCallMetadata.from_sdk(
            function_name='test',
            tool_call_id='call_aaa',
            response_obj=response,
            total_calls_in_response=3,
        )

        assert isinstance(metadata, ToolCallMetadata)

    def test_contains_function_name(self):
        """Test metadata contains function name."""
        response = create_mock_response()
        metadata = ToolCallMetadata.from_sdk(
            function_name='execute_code',
            tool_call_id='call_001',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata.function_name == 'execute_code'

    def test_contains_tool_call_id(self):
        """Test metadata contains tool call ID."""
        response = create_mock_response()
        metadata = ToolCallMetadata.from_sdk(
            function_name='read_file',
            tool_call_id='call_unique_123',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata.tool_call_id == 'call_unique_123'

    def test_contains_total_calls_count(self):
        """Test metadata contains total calls in response."""
        response = create_mock_response()
        metadata = ToolCallMetadata.from_sdk(
            function_name='func',
            tool_call_id='call_x',
            response_obj=response,
            total_calls_in_response=5,
        )

        assert metadata.total_calls_in_response == 5

    def test_model_response_is_dict(self):
        """Test model_response is serialized as dict."""
        response = create_mock_response('chatcmpl-222')

        metadata = ToolCallMetadata.from_sdk(
            function_name='func',
            tool_call_id='call_y',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert isinstance(metadata.model_response, dict)

    def test_raw_response_not_in_public_fields(self):
        """Test _raw_response is private and not serialized."""
        response = create_mock_response()
        metadata = ToolCallMetadata.from_sdk(
            function_name='func',
            tool_call_id='call_z',
            response_obj=response,
            total_calls_in_response=1,
        )

        dumped = metadata.model_dump()
        assert '_raw_response' not in dumped

    def test_can_serialize_to_dict(self):
        """Test can serialize metadata to dictionary."""
        response = create_mock_response('chatcmpl-333')

        metadata = ToolCallMetadata.from_sdk(
            function_name='my_function',
            tool_call_id='call_serialize',
            response_obj=response,
            total_calls_in_response=2,
        )

        dumped = metadata.model_dump()
        assert dumped['function_name'] == 'my_function'
        assert dumped['tool_call_id'] == 'call_serialize'
        assert dumped['total_calls_in_response'] == 2

    def test_preserves_original_response_object(self):
        """Test preserves reference to original SDK response."""
        response = create_mock_response()
        response.custom_field = 'test_value'

        metadata = ToolCallMetadata.from_sdk(
            function_name='func',
            tool_call_id='call_preserve',
            response_obj=response,
            total_calls_in_response=1,
        )

        assert metadata._raw_response.custom_field == 'test_value'

    def test_multiple_instances_have_independent_raw_responses(self):
        """Test multiple instances maintain independent raw responses."""
        response1 = MagicMock()
        response1.id = 'resp1'
        response1.model = 'gpt-4'
        response1.choices = []
        response2 = MagicMock()
        response2.id = 'resp2'
        response2.model = 'gpt-4'
        response2.choices = []

        metadata1 = ToolCallMetadata.from_sdk(
            function_name='func1',
            tool_call_id='call1',
            response_obj=response1,
            total_calls_in_response=1,
        )
        metadata2 = ToolCallMetadata.from_sdk(
            function_name='func2',
            tool_call_id='call2',
            response_obj=response2,
            total_calls_in_response=1,
        )

        assert metadata1._raw_response.id == 'resp1'
        assert metadata2._raw_response.id == 'resp2'
