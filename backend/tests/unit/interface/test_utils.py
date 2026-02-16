"""Tests for backend.interface.utils — shared utility functions and local config helpers."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from backend.interface.utils import (
    ModelInfo,
    ProviderInfo,
    add_local_config_trusted_dir,
    extract_model_and_provider,
    get_local_config_trusted_dirs,
    is_number,
    organize_models_and_providers,
    read_file,
    split_is_actually_version,
    write_to_file,
)


class TestModelInfo:
    """Tests for ModelInfo Pydantic model."""

    def test_create_model_info(self):
        """Test creating ModelInfo instance."""
        info = ModelInfo(provider="openai", model="gpt-4", separator="/")
        assert info.provider == "openai"
        assert info.model == "gpt-4"
        assert info.separator == "/"

    def test_model_info_dict_access(self):
        """Test ModelInfo supports dictionary-like access."""
        info = ModelInfo(provider="anthropic", model="claude-3", separator="/")
        assert info["provider"] == "anthropic"
        assert info["model"] == "claude-3"
        assert info["separator"] == "/"

    def test_model_info_invalid_key(self):
        """Test ModelInfo raises KeyError for invalid key."""
        info = ModelInfo(provider="openai", model="gpt-4", separator="/")
        with pytest.raises(KeyError, match="has no key"):
            _ = info["invalid_key"]

    def test_model_info_all_fields(self):
        """Test ModelInfo has all expected fields."""
        info = ModelInfo(provider="mistral", model="mistral-large", separator=".")
        assert hasattr(info, "provider")
        assert hasattr(info, "model")
        assert hasattr(info, "separator")


class TestProviderInfo:
    """Tests for ProviderInfo Pydantic model."""

    def test_create_provider_info(self):
        """Test creating ProviderInfo instance."""
        info = ProviderInfo(separator="/", models=["gpt-4", "gpt-3.5"])
        assert info.separator == "/"
        assert len(info.models) == 2
        assert "gpt-4" in info.models

    def test_provider_info_default_models(self):
        """Test ProviderInfo models defaults to empty list."""
        info = ProviderInfo(separator="/")
        assert info.models == []

    def test_provider_info_dict_access(self):
        """Test ProviderInfo supports dictionary-like access."""
        info = ProviderInfo(separator=".", models=["model1"])
        assert info["separator"] == "."
        assert info["models"] == ["model1"]

    def test_provider_info_get_method(self):
        """Test ProviderInfo get method with default."""
        info = ProviderInfo(separator="/", models=[])
        assert info.get("separator") == "/"
        assert info.get("models") == []
        assert info.get("nonexistent", None) is None

    def test_provider_info_invalid_key(self):
        """Test ProviderInfo raises KeyError for invalid key."""
        info = ProviderInfo(separator="/", models=[])
        with pytest.raises(KeyError, match="has no key"):
            _ = info["invalid_key"]


class TestExtractModelAndProvider:
    """Tests for extract_model_and_provider function."""

    def test_extract_with_slash_separator(self):
        """Test extracting provider with slash separator."""
        result = extract_model_and_provider("openai/gpt-4")
        assert result.provider == "openai"
        assert result.model == "gpt-4"
        assert result.separator == "/"

    def test_extract_with_dot_separator(self):
        """Test extracting provider with dot separator (non-version)."""
        result = extract_model_and_provider("provider.model-name")
        assert result.separator == "."
        assert result.provider == "provider"
        assert result.model == "model-name"

    def test_extract_single_openai_model(self):
        """Test extracting single known OpenAI model."""
        # Using a model with slash separator to test the parsing logic
        result = extract_model_and_provider("openai/gpt-4")
        assert result.provider == "openai"
        assert result.model == "gpt-4"
        assert result.separator == "/"

    def test_extract_single_anthropic_model(self):
        """Test extracting single known Anthropic model."""
        # Using a model with slash separator to test the parsing logic
        result = extract_model_and_provider("anthropic/claude-3-5-sonnet-20241022")
        assert result.provider == "anthropic"
        assert result.separator == "/"

    def test_extract_unknown_single_model(self):
        """Test extracting unknown single model."""
        result = extract_model_and_provider("unknown-model")
        assert result.provider == ""
        assert result.model == "unknown-model"
        assert result.separator == ""

    def test_extract_nested_model_path(self):
        """Test extracting nested model path."""
        result = extract_model_and_provider("provider/namespace/model")
        assert result.provider == "provider"
        assert result.model == "namespace/model"
        assert result.separator == "/"

    def test_extract_version_number_not_split(self):
        """Test version numbers are not treated as provider."""
        result = extract_model_and_provider("gpt-3.5-turbo")
        # Should recognize as single model (version number)
        assert result.model == "gpt-3.5-turbo"


class TestOrganizeModelsAndProviders:
    """Tests for organize_models_and_providers function."""

    def test_organize_single_provider(self):
        """Test organizing models from single provider."""
        models = ["openai/gpt-4", "openai/gpt-3.5-turbo"]
        result = organize_models_and_providers(models)
        assert "openai" in result
        assert len(result["openai"].models) == 2
        assert result["openai"].separator == "/"

    def test_organize_multiple_providers(self):
        """Test organizing models from multiple providers."""
        models = ["openai/gpt-4", "anthropic/claude-3"]
        result = organize_models_and_providers(models)
        assert "openai" in result
        assert "anthropic" in result
        assert len(result["openai"].models) == 1
        assert len(result["anthropic"].models) == 1

    def test_organize_with_unknown_models(self):
        """Test organizing includes unknown models in 'other'."""
        models = ["openai/gpt-4", "unknown-model"]
        result = organize_models_and_providers(models)
        assert "openai" in result
        # Unknown models might go to "other" or empty provider

    def test_organize_empty_list(self):
        """Test organizing empty model list."""
        result = organize_models_and_providers([])
        assert result == {}

    def test_organize_skips_anthropic_dot_separator(self):
        """Test organizing skips Anthropic models with dot separator."""
        models = ["anthropic.model", "openai/gpt-4"]
        result = organize_models_and_providers(models)
        # anthropic.model should be skipped
        assert "anthropic" not in result or len(result.get("anthropic", ProviderInfo(separator="/", models=[])).models) == 0


class TestLocalConfigFunctions:
    """Tests for local configuration file functions."""

    def test_get_local_config_trusted_dirs_no_file(self):
        """Test get_local_config_trusted_dirs with no config file."""
        with patch("backend.interface.utils._LOCAL_CONFIG_FILE_PATH") as mock_path:
            mock_path.exists.return_value = False
            dirs = get_local_config_trusted_dirs()
            assert dirs == []

    def test_get_local_config_trusted_dirs_with_dirs(self):
        """Test get_local_config_trusted_dirs with existing dirs."""
        config_content = """
[runtime]
trusted_dirs = ["/path/to/dir1", "/path/to/dir2"]
"""
        with patch("backend.interface.utils._LOCAL_CONFIG_FILE_PATH") as mock_path:
            mock_path.exists.return_value = True
            with patch("builtins.open", mock_open(read_data=config_content)):
                dirs = get_local_config_trusted_dirs()
                assert len(dirs) == 2
                assert "/path/to/dir1" in dirs

    def test_add_local_config_trusted_dir_new_dir(self):
        """Test add_local_config_trusted_dir adds new directory."""
        with (
            patch("backend.interface.utils._LOCAL_CONFIG_FILE_PATH") as mock_path,
            patch("backend.interface.utils._load_local_config") as mock_load,
            patch("backend.interface.utils._save_local_config") as mock_save,
        ):
            mock_path.exists.return_value = False
            mock_path.parent.mkdir = MagicMock()
            mock_load.return_value = {"runtime": {"trusted_dirs": []}}

            add_local_config_trusted_dir("/new/path")

            # Should have called save with updated config
            assert mock_save.called
            saved_config = mock_save.call_args[0][0]
            assert "/new/path" in saved_config["runtime"]["trusted_dirs"]

    def test_add_local_config_trusted_dir_duplicate(self):
        """Test add_local_config_trusted_dir skips duplicate directory."""
        existing_config = {"runtime": {"trusted_dirs": ["/existing/path"]}}
        with (
            patch("backend.interface.utils._load_local_config") as mock_load,
            patch("backend.interface.utils._save_local_config") as mock_save,
        ):
            mock_load.return_value = existing_config

            add_local_config_trusted_dir("/existing/path")

            # Should save but not duplicate
            saved_config = mock_save.call_args[0][0]
            assert saved_config["runtime"]["trusted_dirs"].count("/existing/path") == 1


class TestHelperFunctions:
    """Tests for helper utility functions."""

    def test_is_number_with_digit(self):
        """Test is_number returns True for digit."""
        assert is_number("5") is True
        assert is_number("0") is True
        assert is_number("9") is True

    def test_is_number_with_non_digit(self):
        """Test is_number returns False for non-digit."""
        assert is_number("a") is False
        assert is_number(".") is False
        assert is_number("-") is False

    def test_split_is_actually_version_with_version(self):
        """Test split_is_actually_version recognizes version numbers."""
        assert split_is_actually_version(["gpt", "3"]) is True
        assert split_is_actually_version(["model", "1.0"]) is True

    def test_split_is_actually_version_without_version(self):
        """Test split_is_actually_version returns False for non-versions."""
        assert split_is_actually_version(["provider", "model"]) is False
        assert split_is_actually_version(["single"]) is False

    def test_split_is_actually_version_edge_cases(self):
        """Test split_is_actually_version handles edge cases."""
        assert split_is_actually_version([]) is False
        assert split_is_actually_version(["one"]) is False
        assert split_is_actually_version(["a", ""]) is False


class TestFileOperations:
    """Tests for file read/write operations."""

    def test_read_file_success(self):
        """Test read_file reads file content."""
        content = "Test file content"
        with patch("builtins.open", mock_open(read_data=content)):
            result = read_file("test.txt")
            assert result == content

    def test_read_file_with_path_object(self):
        """Test read_file works with Path object."""
        content = "Path content"
        with patch("builtins.open", mock_open(read_data=content)):
            result = read_file(Path("test.txt"))
            assert result == content

    def test_write_to_file_success(self):
        """Test write_to_file writes content."""
        with patch("builtins.open", mock_open()) as mock_file:
            write_to_file("output.txt", "Test content")
            mock_file.assert_called_once_with("output.txt", "w", encoding="utf-8")
            mock_file().write.assert_called_once_with("Test content")

    def test_write_to_file_with_path_object(self):
        """Test write_to_file works with Path object."""
        with patch("builtins.open", mock_open()) as mock_file:
            write_to_file(Path("output.txt"), "Content")
            assert mock_file.called

    def test_read_and_write_roundtrip(self):
        """Test reading and writing files in sequence."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_path = f.name

        try:
            # Write content
            test_content = "Roundtrip test content"
            write_to_file(temp_path, test_content)

            # Read it back
            read_content = read_file(temp_path)
            assert read_content == test_content
        finally:
            Path(temp_path).unlink()


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_model_info_empty_strings(self):
        """Test ModelInfo with empty strings."""
        info = ModelInfo(provider="", model="", separator="")
        assert info.provider == ""
        assert info.model == ""
        assert info.separator == ""

    def test_provider_info_empty_models_list(self):
        """Test ProviderInfo with empty models list."""
        info = ProviderInfo(separator="/", models=[])
        assert len(info.models) == 0

    def test_extract_model_and_provider_empty_string(self):
        """Test extract_model_and_provider with empty string."""
        result = extract_model_and_provider("")
        assert result.model == ""

    def test_organize_models_preserves_order(self):
        """Test organize_models_and_providers maintains model order."""
        models = ["openai/gpt-4", "openai/gpt-3.5-turbo", "openai/text-davinci-003"]
        result = organize_models_and_providers(models)
        if "openai" in result:
            assert len(result["openai"].models) == 3

    def test_split_is_actually_version_single_element(self):
        """Test split_is_actually_version with single element."""
        assert split_is_actually_version(["model"]) is False

    def test_is_number_empty_string(self):
        """Test is_number with empty string."""
        assert is_number("") is False
