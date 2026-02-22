"""Model alias system for flexible model configuration.

Allows users to define semantic aliases (e.g., "my-coding-model", "fast-chat")
that map to specific models, making it easy to switch between cloud and local
models without changing agent configurations.
"""

from __future__ import annotations

import functools
import os
import tomllib  # Python 3.11+
from pathlib import Path
from typing import Any

from backend.core.logger import forge_logger as logger


class ModelAliasManager:
    """Manages model aliases for flexible model configuration."""

    def __init__(self):
        self._aliases: dict[str, str] = {}
        self._loaded = False

    def load_aliases(self, config_path: Path | None = None) -> None:
        """Load model aliases from configuration.

        Args:
            config_path: Path to config file. If None, uses default locations.
        """
        if self._loaded:
            return

        # Try multiple locations
        search_paths = []

        if config_path:
            search_paths.append(config_path)

        # Check current directory
        search_paths.append(Path("config.toml"))

        # Check home directory
        home_config = Path.home() / ".forge" / "config.toml"
        search_paths.append(home_config)

        # Check environment variable
        env_config = os.getenv("FORGE_CONFIG")
        if env_config:
            search_paths.append(Path(env_config))

        for path in search_paths:
            if path.exists():
                try:
                    self._load_from_file(path)
                    logger.info("Loaded model aliases from %s", path)
                    self._loaded = True
                    return
                except Exception as e:
                    logger.debug("Failed to load aliases from %s: %s", path, e)

        logger.debug("No model aliases configuration found")
        self._loaded = True

    def _load_from_file(self, path: Path) -> None:
        """Load aliases from a TOML file.

        Expected format:
        [model_aliases]
        my-coding-model = "claude-3-7-sonnet"
        fast-chat = "ollama/llama3.2"
        local-coder = "ollama/qwen2.5-coder"
        """
        with open(path, "rb") as f:
            data = tomllib.load(f)

        aliases = data.get("model_aliases", {})
        for alias, target in aliases.items():
            if isinstance(target, str):
                self._aliases[alias] = target
                logger.debug("Loaded alias: %s -> %s", alias, target)

    def resolve_alias(self, model_or_alias: str) -> str:
        """Resolve a model alias to its target model.

        Args:
            model_or_alias: Model name or alias

        Returns:
            Resolved model name (or original if not an alias)
        """
        if not self._loaded:
            self.load_aliases()

        resolved = self._aliases.get(model_or_alias, model_or_alias)

        if resolved != model_or_alias:
            logger.debug("Resolved alias %s -> %s", model_or_alias, resolved)

        return resolved

    def add_alias(self, alias: str, target: str) -> None:
        """Add or update a model alias.

        Args:
            alias: Alias name
            target: Target model name
        """
        self._aliases[alias] = target
        logger.info("Added alias: %s -> %s", alias, target)

    def remove_alias(self, alias: str) -> bool:
        """Remove a model alias.

        Args:
            alias: Alias name to remove

        Returns:
            True if alias was removed, False if it didn't exist
        """
        if alias in self._aliases:
            del self._aliases[alias]
            logger.info("Removed alias: %s", alias)
            return True
        return False

    def get_all_aliases(self) -> dict[str, str]:
        """Get all defined aliases.

        Returns:
            Dictionary mapping aliases to target models
        """
        if not self._loaded:
            self.load_aliases()
        return self._aliases.copy()

    def is_alias(self, name: str) -> bool:
        """Check if a name is a defined alias.

        Args:
            name: Name to check

        Returns:
            True if name is an alias
        """
        if not self._loaded:
            self.load_aliases()
        return name in self._aliases

    def save_aliases(self, path: Path) -> None:
        """Save current aliases to a TOML file.

        Args:
            path: Path to save aliases to
        """
        try:
            import tomli_w

            # Read existing config if it exists
            config: dict[str, Any] = {}
            if path.exists():
                with open(path, "rb") as f:
                    config = tomllib.load(f)

            # Update aliases section
            config["model_aliases"] = self._aliases

            # Write back
            with open(path, "wb") as f:
                f.write(tomli_w.dumps(config).encode("utf-8"))

            logger.info("Saved %d aliases to %s", len(self._aliases), path)
        except ImportError:
            logger.error(
                "tomli-w package not available for writing. Install with: pip install tomli-w"
            )
        except Exception as e:
            logger.error("Failed to save aliases: %s", e)


# Global alias manager instance
@functools.lru_cache(maxsize=1)
def get_alias_manager() -> ModelAliasManager:
    """Get the global model alias manager instance."""
    return ModelAliasManager()
