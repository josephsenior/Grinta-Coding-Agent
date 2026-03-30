"""Tests for backend.gateway.adapters.json custom JSON serialization."""

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from backend.gateway.adapters.json import AppJSONEncoder, dumps, loads
from backend.core.errors import LLMResponseError


class SampleModel(BaseModel):
    """Sample Pydantic model for testing."""

    name: str
    value: int


class TestAppJSONEncoder:
    """Tests for AppJSONEncoder custom encoder."""

    def test_encode_datetime(self):
        """Test datetime serialization."""
        dt = datetime(2024, 1, 15, 10, 30, 45)
        encoder = AppJSONEncoder()
        result = encoder.encode({"timestamp": dt})
        assert "2024-01-15T10:30:45" in result

    def test_encode_event_object(self):
        """Test Event object serialization."""
        from backend.ledger.action import NullAction

        # Create real event instance
        event = NullAction()

        encoder = AppJSONEncoder()
        # Should use event_to_dict which internally calls appropriate serialization
        result = encoder.default(event)
        assert isinstance(result, dict)
        assert "action" in result

    def test_encode_metrics(self):
        """Test Metrics object serialization."""
        from backend.inference.metrics import Metrics

        metrics = MagicMock(spec=Metrics)
        metrics.get.return_value = {"tokens": 100, "cost": 0.01}

        encoder = AppJSONEncoder()
        result = encoder.default(metrics)
        assert result == {"tokens": 100, "cost": 0.01}

    def test_encode_base_model(self):
        """Test Pydantic BaseModel serialization."""
        model = SampleModel(name="test", value=42)
        encoder = AppJSONEncoder()
        result = encoder.default(model)
        assert result == {"name": "test", "value": 42}

    def test_encode_cmd_output_metadata(self):
        """Test CmdOutputMetadata serialization."""
        from backend.ledger.observation import CmdOutputMetadata

        metadata = CmdOutputMetadata(exit_code=0, pid=123)
        encoder = AppJSONEncoder()
        result = encoder.default(metadata)
        assert isinstance(result, dict)
        assert result["exit_code"] == 0
        assert result["pid"] == 123

    def test_encode_object_with_model_dump(self):
        """Test objects with model_dump method."""
        obj = MagicMock()
        obj.model_dump.return_value = {"field": "value"}

        encoder = AppJSONEncoder()
        result = encoder.default(obj)
        assert result == {"field": "value"}

    def test_encode_unsupported_type(self):
        """Test encoding unsupported type raises TypeError."""
        encoder = AppJSONEncoder()

        class CustomClass:
            pass

        with pytest.raises(TypeError):
            encoder.default(CustomClass())

    def test_encode_nested_datetime(self):
        """Test nested datetime in dict."""
        dt = datetime(2024, 6, 1, 12, 0, 0)
        data = {"info": {"created": dt}}
        encoder = AppJSONEncoder()
        result = encoder.encode(data)
        assert "2024-06-01T12:00:00" in result

    def test_encode_list_of_datetimes(self):
        """Test list containing datetimes."""
        dt1 = datetime(2024, 1, 1)
        dt2 = datetime(2024, 12, 31)
        encoder = AppJSONEncoder()
        result = encoder.encode([dt1, dt2])
        assert "2024-01-01" in result
        assert "2024-12-31" in result


class TestDumps:
    """Tests for dumps function."""

    def test_dumps_basic_types(self):
        """Test dumping basic types."""
        result = dumps({"key": "value", "num": 42})
        assert json.loads(result) == {"key": "value", "num": 42}

    def test_dumps_with_datetime(self):
        """Test dumping datetime uses AppJSONEncoder."""
        dt = datetime(2024, 3, 15)
        result = dumps({"date": dt})
        assert "2024-03-15" in result

    def test_dumps_with_base_model(self):
        """Test dumping Pydantic model."""
        model = SampleModel(name="test", value=99)
        result = dumps({"model": model})
        data = json.loads(result)
        assert data["model"]["name"] == "test"
        assert data["model"]["value"] == 99

    def test_dumps_no_kwargs(self):
        """Test dumps without kwargs uses shared encoder."""
        result = dumps({"test": "value"})
        assert json.loads(result) == {"test": "value"}

    def test_dumps_with_custom_kwargs(self):
        """Test dumps with custom kwargs (indent, etc)."""
        result = dumps({"key": "value"}, indent=2)
        assert "\n" in result  # Indented output
        assert json.loads(result) == {"key": "value"}

    def test_dumps_with_custom_encoder_class(self):
        """Test dumps with custom encoder class."""

        class CustomEncoder(json.JSONEncoder):
            def default(self, obj):
                if isinstance(obj, set):
                    return list(obj)
                return super().default(obj)

        result = dumps({"items": {1, 2, 3}}, cls=CustomEncoder)
        data = json.loads(result)
        assert set(data["items"]) == {1, 2, 3}

    def test_dumps_preserves_app_encoder_when_no_cls(self):
        """Test dumps uses AppJSONEncoder when no cls specified."""
        dt = datetime(2024, 7, 4)
        result = dumps({"date": dt}, indent=2)
        assert "2024-07-04" in result

    def test_dumps_empty_dict(self):
        """Test dumping empty dict."""
        assert dumps({}) == "{}"

    def test_dumps_empty_list(self):
        """Test dumping empty list."""
        assert dumps([]) == "[]"

    def test_dumps_nested_structure(self):
        """Test dumping complex nested structure."""
        data = {
            "models": [SampleModel(name=f"model{i}", value=i) for i in range(3)],
            "timestamp": datetime(2024, 1, 1),
        }
        result = dumps(data)
        parsed = json.loads(result)
        assert len(parsed["models"]) == 3
        assert "2024-01-01" in result


class TestLoads:
    """Tests for loads function — includes repair logic."""

    def test_loads_valid_json(self):
        """Test loading valid JSON."""
        result = loads('{"key": "value", "num": 42}')
        assert result == {"key": "value", "num": 42}

    def test_loads_valid_json_with_kwargs(self):
        """Test loading with custom kwargs."""
        result = loads('{"a": 1}', parse_int=lambda x: int(x) * 2)
        assert result["a"] == 2

    def test_loads_json_embedded_in_text(self):
        """Test extracting JSON from text with prefix/suffix."""
        text = 'Some preamble text {"key": "value"} trailing text'
        result = loads(text)
        assert result == {"key": "value"}

    def test_loads_json_repair_for_invalid(self):
        """Test JSON repair for malformed JSON."""
        # This will extract the JSON object and attempt repair
        text = 'prefix {"key": "value",} suffix'
        result = loads(text)
        assert "key" in result

    def test_loads_nested_braces_extraction(self):
        """Test extraction with nested braces."""
        text = 'text {"outer": {"inner": "value"}} more text'
        result = loads(text)
        assert result == {"outer": {"inner": "value"}}

    def test_loads_no_json_object_raises_error(self):
        """Test error when no JSON object found."""
        with pytest.raises(LLMResponseError, match="No valid JSON object found"):
            loads("just plain text with no braces")

    def test_loads_invalid_json_raises_error_after_repair(self):
        """Test error when repair also fails."""
        # Completely broken JSON that can't be repaired
        with pytest.raises(LLMResponseError, match="No valid JSON"):
            loads("prefix {broken{nested{unterminated suffix")

    def test_loads_empty_json_object(self):
        """Test loading empty JSON object."""
        result = loads("{}")
        assert result == {}

    def test_loads_json_array(self):
        """Test loading JSON array actually works with default JSON."""
        # Array is valid JSON, so standard json.loads works
        result = loads("[1, 2, 3]")
        assert result == [1, 2, 3]

    def test_loads_multiple_json_objects_returns_first(self):
        """Test with multiple JSON objects returns first complete one."""
        text = '{"first": 1} {"second": 2}'
        result = loads(text)
        assert result == {"first": 1}

    def test_loads_json_with_escaped_quotes(self):
        """Test JSON with escaped quotes."""
        text = '{"message": "He said \\"hello\\""}'
        result = loads(text)
        assert result["message"] == 'He said "hello"'

    def test_loads_json_with_unicode(self):
        """Test JSON with unicode characters."""
        text = '{"emoji": "🚀", "text": "Hello 世界"}'
        result = loads(text)
        assert result["emoji"] == "🚀"
        assert result["text"] == "Hello 世界"

    def test_loads_json_after_malformed_prefix(self):
        """Test extraction after malformed text."""
        text = 'Error: something went wrong\n{"status": "recovered"}'
        result = loads(text)
        assert result == {"status": "recovered"}

    def test_loads_deeply_nested_json(self):
        """Test deeply nested JSON structure."""
        text = '{"a": {"b": {"c": {"d": "deep"}}}}'
        result = loads(text)
        assert result["a"]["b"]["c"]["d"] == "deep"

    def test_loads_json_with_numbers_and_bools(self):
        """Test JSON with various value types."""
        text = '{"int": 42, "float": 3.14, "bool": true, "null": null}'
        result = loads(text)
        assert result["int"] == 42
        assert result["float"] == 3.14
        assert result["bool"] is True
        assert result["null"] is None
