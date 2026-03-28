"""Helpers for constructing runtime startup commands and validating parameters."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.constants import (
    DEFAULT_MAIN_MODULE,
    DEFAULT_PYTHON_PREFIX,
)
from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.core.config import ForgeConfig
    from backend.execution.plugins import PluginRequirement


def _build_plugin_args(plugins: list[PluginRequirement] | None) -> list[str]:
    """Build plugin arguments for command.

    Args:
        plugins: List of plugin requirements

    Returns:
        Plugin arguments list

    """
    if not plugins:
        return []
    return ["--plugins"] + [plugin.name for plugin in plugins]


def _validate_and_get_username(
    override_username: str | None, run_as_forge: bool
) -> str:
    """Validate and get username with security checks.

    Args:
        override_username: Override username if provided
        run_as_forge: Whether to run as forge user

    Returns:
        Validated username

    """
    default_username = "forge" if run_as_forge else "root"
    username = override_username or default_username

    # Validate username to prevent command injection
    dangerous_chars = [
        ";",
        "&",
        "|",
        "`",
        "$",
        "(",
        ")",
        "<",
        ">",
        '"',
        "'",
        "\\",
        " ",
        "\n",
        "\t",
    ]
    if any(char in username for char in dangerous_chars):
        logger.warning("Invalid characters in username, using default")
        return default_username

    return username


def _validate_env_part(part: object) -> bool:
    """Validate a single environment/CLI token to reduce injection risk.

    The goal is to reject shell metacharacters and other suspicious
    characters. This is intentionally conservative.
    """
    if not isinstance(part, str):
        return False
    if not part:
        return False

    dangerous_chars = [
        ";",
        "&",
        "|",
        "`",
        "$",
        "(",
        ")",
        "<",
        ">",
        '"',
        "'",
        "\\",
        " ",
        "\n",
        "\t",
    ]
    if any(char in part for char in dangerous_chars):
        return False
    return True


def get_action_execution_server_startup_command(
    server_port: int,
    plugins: list[PluginRequirement],
    app_config: ForgeConfig,
    python_prefix: list[str] | None = None,
    override_user_id: int | None = None,
    override_username: str | None = None,
    main_module: str = DEFAULT_MAIN_MODULE,
    python_executable: str = "python",
) -> list[str]:
    """Generate the startup command for the action execution server.

    Args:
        server_port: The port number for the server.
        plugins: List of plugin requirements.
        app_config: Forge configuration object.
        python_prefix: Python command prefix (default: micromamba with uv).
        override_user_id: Override user ID for the server process.
        override_username: Override username for the server process.
        main_module: Main module to execute (default: action_execution_server).
        python_executable: Python executable to use.

    Returns:
        list[str]: Command arguments for starting the action execution server.

    """
    runtime_config = app_config.runtime_config
    logger.debug("app_config %s", vars(app_config))
    logger.debug("runtime_config %s", vars(runtime_config))
    logger.debug("override_user_id %s", override_user_id)

    # Build command components
    plugin_args = _build_plugin_args(plugins)
    username = _validate_and_get_username(override_username, app_config.run_as_Forge)
    user_id = override_user_id or (1000 if app_config.run_as_Forge else 0)

    # Build base command
    effective_prefix = (
        python_prefix if python_prefix is not None else DEFAULT_PYTHON_PREFIX
    )
    base_cmd = [
        *effective_prefix,
        python_executable,
        "-u",
        "-m",
        main_module,
        str(server_port),
        "--working-dir",
        app_config.workspace_mount_path_in_runtime,
        *plugin_args,
        "--username",
        username,
        "--user-id",
        str(user_id),
    ]

    if not app_config.enable_browser:
        base_cmd.append("--no-enable-browser")

    logger.debug("get_action_execution_server_startup_command: %s", base_cmd)
    # Filter out None values to ensure return type is list[str]
    return [item for item in base_cmd if item is not None]
