"""Shared utility functions and local config helpers for the Forge CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import json

from pydantic import BaseModel, Field

from backend.core.app_paths import get_app_settings_root
from backend.core.providers import (
    VERIFIED_ANTHROPIC_MODELS,
    VERIFIED_MISTRAL_MODELS,
    VERIFIED_OPENAI_MODELS,
)

if TYPE_CHECKING:
    pass

def _canonical_settings_path() -> Path:
    """Same file the server uses — :func:`get_app_settings_root` / ``settings.json``."""
    return Path(get_app_settings_root()) / "settings.json"


_DEFAULT_CONFIG: dict[str, dict[str, list[str]]] = {"runtime": {"trusted_dirs": []}}


def get_local_config_trusted_dirs() -> list[str]:
    """Get trusted directories from local configuration.

    Returns:
        list[str]: List of trusted directory paths from local config.

    """
    path = _canonical_settings_path()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            try:
                config = json.load(f)
            except Exception:
                config = _DEFAULT_CONFIG
        if "runtime" in config and "trusted_dirs" in config["runtime"]:
            return config["runtime"]["trusted_dirs"]
    return []


def _load_local_config() -> dict:
    """Load local config file or return default config."""
    path = _canonical_settings_path()
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return _DEFAULT_CONFIG
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        return _DEFAULT_CONFIG


def _ensure_runtime_config(config: dict) -> None:
    """Ensure runtime section exists in config."""
    if "runtime" not in config:
        config["runtime"] = {}
    if "trusted_dirs" not in config["runtime"]:
        config["runtime"]["trusted_dirs"] = []


def _add_trusted_dir(config: dict, folder_path: str) -> None:
    """Add folder path to trusted directories if not already present."""
    if folder_path not in config["runtime"]["trusted_dirs"]:
        config["runtime"]["trusted_dirs"].append(folder_path)


def _save_local_config(config: dict) -> None:
    """Save config to local config file."""
    path = _canonical_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def add_local_config_trusted_dir(folder_path: str) -> None:
    """Add a folder path to trusted directories in local config.

    Args:
        folder_path: The path to add to trusted directories.

    """
    config = _load_local_config()
    _ensure_runtime_config(config)
    _add_trusted_dir(config, folder_path)
    _save_local_config(config)


class ModelInfo(BaseModel):
    """Information about a model and its provider."""

    provider: str = Field(description="The provider of the model")
    model: str = Field(description="The model identifier")
    separator: str = Field(description="The separator used in the model identifier")

    def __getitem__(self, key: str) -> str:
        """Allow dictionary-like access to fields."""
        if key == "provider":
            return self.provider
        if key == "model":
            return self.model
        if key == "separator":
            return self.separator
        msg = f"ModelInfo has no key {key}"
        raise KeyError(msg)


def extract_model_and_provider(model: str) -> ModelInfo:
    """Extract provider and model information from a model identifier.

    Args:
        model: The model identifier string

    Returns:
        A ModelInfo object containing provider, model, and separator information

    """
    separator = "/"
    split = model.split(separator)
    if len(split) == 1:
        separator = "."
        split = model.split(separator)
        if split_is_actually_version(split):
            split = [separator.join(split)]
    if len(split) == 1:
        if split[0] in VERIFIED_OPENAI_MODELS:
            return ModelInfo(provider="openai", model=split[0], separator="/")
        if split[0] in VERIFIED_ANTHROPIC_MODELS:
            return ModelInfo(provider="anthropic", model=split[0], separator="/")
        if split[0] in VERIFIED_MISTRAL_MODELS:
            return ModelInfo(provider="mistral", model=split[0], separator="/")
        return ModelInfo(provider="", model=model, separator="")
    provider = split[0]
    model_id = separator.join(split[1:])
    return ModelInfo(provider=provider, model=model_id, separator=separator)


def _should_skip_model(provider: str, separator: str) -> bool:
    """Check if model should be skipped based on provider and separator.

    Args:
        provider: The model provider.
        separator: The separator used in the model identifier.

    Returns:
        bool: True if the model should be skipped, False otherwise.

    """
    return provider == "anthropic" and separator == "."


def _get_provider_key(provider: str | None) -> str:
    """Get the provider key for the result dictionary."""
    return provider or "other"


def _add_model_to_provider(
    result_dict: dict[str, ProviderInfo],
    provider_key: str,
    separator: str,
    model_id: str,
) -> None:
    """Add model to the appropriate provider in the result dictionary."""
    if provider_key not in result_dict:
        result_dict[provider_key] = ProviderInfo(separator=separator, models=[])
    result_dict[provider_key].models.append(model_id)


def organize_models_and_providers(models: list[str]) -> dict[str, ProviderInfo]:
    """Organize a list of model identifiers by provider.

    Args:
        models: List of model identifiers

    Returns:
        A mapping of providers to their information and models

    """
    result_dict: dict[str, ProviderInfo] = {}
    for model in models:
        extracted = extract_model_and_provider(model)
        separator = extracted.separator
        provider = extracted.provider
        model_id = extracted.model

        if _should_skip_model(provider, separator):
            continue

        provider_key = _get_provider_key(provider)
        _add_model_to_provider(result_dict, provider_key, separator, model_id)

    return result_dict


class ProviderInfo(BaseModel):
    """Information about a provider and its models."""

    separator: str = Field(description="The separator used in model identifiers")
    models: list[str] = Field(
        default_factory=list, description="List of model identifiers"
    )

    def __getitem__(self, key: str) -> str | list[str]:
        """Allow dictionary-like access to fields."""
        if key == "separator":
            return self.separator
        if key == "models":
            return self.models
        msg = f"ProviderInfo has no key {key}"
        raise KeyError(msg)

    def get(self, key: str, default: None = None) -> str | list[str] | None:
        """Dictionary-like get method with default value."""
        try:
            return self[key]
        except KeyError:
            return default


def is_number(s: str) -> bool:
    """Check if a character is a digit.

    Args:
        s: The character to check.

    Returns:
        bool: True if the character is a digit, False otherwise.

    """
    return s.isdigit()


def split_is_actually_version(split: list[str]) -> bool:
    """Check if a split represents a version number.

    Args:
        split: List of strings to check.

    Returns:
        bool: True if the split represents a version, False otherwise.

    """
    return (
        len(split) > 1
        and bool(split[1])
        and bool(split[1][0])
        and is_number(split[1][0])
    )


def read_file(file_path: str | Path) -> str:
    """Read the contents of a file.

    Args:
        file_path: The path to the file to read.

    Returns:
        str: The contents of the file.

    """
    with open(file_path, encoding="utf-8") as f:
        return f.read()


def write_to_file(file_path: str | Path, content: str) -> None:
    """Write content to a file.

    Args:
        file_path: The path to the file to write to.
        content: The content to write to the file.

    """
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
