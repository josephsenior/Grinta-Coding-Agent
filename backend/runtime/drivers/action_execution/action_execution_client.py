from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import httpx

from backend.runtime.base import Runtime
from backend.runtime.utils.request import send_request
from backend.runtime.utils.system_stats import update_last_execution_time

if TYPE_CHECKING:
    from backend.core.config import ForgeConfig
    from backend.events import EventStream
    from backend.llm.llm_registry import LLMRegistry


logger = logging.getLogger(__name__)


class UnsupportedActionError(NotImplementedError):
    """Raised when a runtime method is not supported on the current platform/config."""


class ActionExecutionClient(Runtime):
    """Base runtime client that dispatches actions to an action-execution server.

    **Capability contract:**

    Every public action method falls into one of three categories:

    * *Always available* — works on all platforms (``run``, ``read``, ``write``,
      ``edit``, ``browse``, ``think``, ``list_files``, ``copy_to``,
      ``check_if_alive``, ``send_action_for_execution``).
    * *Platform-restricted* — only available on non-Windows hosts.  On Windows
      these methods return a typed ``ErrorObservation`` with a clear message
      instead of silently no-opping (``call_tool_mcp``, ``get_mcp_config``).
    * *Not yet implemented* — calling raises ``UnsupportedActionError`` with a
    human-readable message (``copy_from``, ``_upload_file_to_runtime``).

    Subclasses (e.g. ``LocalRuntimeInProcess``) may override any method to
    provide a concrete implementation without changing this contract.
    """

    # Actions that are always dispatched to the server
    _SERVER_ACTIONS: frozenset[str] = frozenset(
        {
            "run",
            "read",
            "write",
            "edit",
            "browse",
            "browse_interactive",
            "think",
            "null",
            "finish_playbook",
        }
    )

    # Actions restricted on Windows
    _WINDOWS_UNSUPPORTED: frozenset[str] = frozenset(
        {
            "call_tool_mcp",
        }
    )

    def __init__(
        self,
        config: ForgeConfig,
        event_stream: EventStream | None,
        llm_registry: LLMRegistry,
        sid: str = "default",
        plugins: list[Any] | None = None,
        env_vars: dict[str, str] | None = None,
        status_callback: Any | None = None,
        attach_to_existing: bool = False,
        headless_mode: bool = False,
        user_id: str | None = None,
        vcs_provider_tokens: Any | None = None,
        workspace_base: str | None = None,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(
            config=config,
            event_stream=event_stream,
            llm_registry=llm_registry,
            sid=sid,
            plugins=plugins,
            env_vars=env_vars,
            status_callback=status_callback,
            attach_to_existing=attach_to_existing,
            headless_mode=headless_mode,
            user_id=user_id,
            vcs_provider_tokens=vcs_provider_tokens,
            workspace_base=workspace_base,
        )
        self._vscode_token: str | None = None

    async def connect(self) -> None:
        pass

    def get_mcp_config(self, extra_stdio_servers: list[Any] | None = None) -> Any:
        if sys.platform == "win32":
            from backend.core.config.mcp_config import MCPConfig

            return MCPConfig()

        resp = self._send_action_server_request("GET", "/mcp_config")  # type: ignore[unreachable]
        data = resp.json()

        from backend.core.config.mcp_config import MCPConfig, MCPSSEServerConfig

        config = MCPConfig(
            sse_servers=data.get("sse_servers", []),
            stdio_servers=data.get("stdio_servers", []),
            shttp_servers=data.get("shttp_servers", []),
        )

        # Add default SSE server if none from server
        if not config.sse_servers:
            config.sse_servers.append(MCPSSEServerConfig(url=f"{getattr(self, 'action_execution_server_url', '')}/mcp"))

        if extra_stdio_servers:
            config.stdio_servers.extend(extra_stdio_servers)
            # Update server if needed
            self._send_action_server_request(
                "POST",
                "/mcp_config",
                json={"stdio_servers": [s.__dict__ for s in config.stdio_servers]},
            )
            self._last_updated_mcp_stdio_servers = config.stdio_servers

        return config

    def run(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def read(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def write(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def edit(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def copy_to(self, host_src: str, runtime_dest: str, recursive: bool = False) -> None:
        import os
        import tempfile
        from zipfile import ZipFile

        if not os.path.exists(host_src):
            raise FileNotFoundError(f"Source path {host_src} does not exist")

        if recursive:
            fd, tmp_path = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            try:
                with ZipFile(tmp_path, "w") as zipf:
                    for root, _, files in os.walk(host_src):
                        for file in files:
                            full_path = os.path.join(root, file)
                            arcname = os.path.relpath(full_path, host_src)
                            zipf.write(full_path, arcname)

                with open(tmp_path, "rb") as f:
                    self._upload_file_to_runtime(f, runtime_dest, recursive, host_src)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        else:
            with open(host_src, "rb") as f:
                self._upload_file_to_runtime(f, runtime_dest, recursive, host_src)

    def copy_from(self, path: str) -> Any:
        raise UnsupportedActionError(
            "copy_from is not implemented in ActionExecutionClient. "
            "Override in a subclass (e.g. LocalRuntimeInProcess) to provide "
            "runtime-to-host file transfer."
        )

    def list_files(self, path: str | None = None, recursive: bool = False) -> list[str]:
        resp = self._send_action_server_request("GET", "/list_files", params={"path": path, "recursive": recursive})
        return resp.json()

    def browse(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def browse_interactive(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    async def call_tool_mcp(self, action: Any) -> Any:
        """Call an MCP tool.  Not available on Windows."""
        if sys.platform == "win32":
            from backend.events.observation import ErrorObservation

            return ErrorObservation(
                content=(
                    "MCP tools are not supported on Windows. "
                    "To use MCP, run Forge on Linux or macOS, or "
                    "use Forge in a Linux/macOS environment."
                )
            )

        raise UnsupportedActionError(
            "call_tool_mcp requires the action-execution server to have "
            "an MCP endpoint configured.  Ensure the runtime supports MCP "
            "or override this method in your runtime subclass."
        )

    def check_if_alive(self) -> None:
        self._send_action_server_request("GET", "/ping")

    def think(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def null(self, action: Any) -> Any:
        return None

    def finish_playbook(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def send_action_for_execution(self, action: Any) -> Any:
        from backend.core.exceptions import AgentRuntimeTimeoutError

        try:
            self._validate_action_type(action)
        except ValueError as e:
            from backend.events.observation import ErrorObservation

            return ErrorObservation(content=str(e))

        if not getattr(action, "runnable", True):
            from backend.events.observation import NullObservation

            return NullObservation(content="")

        update_last_execution_time()
        try:
            return self._execute_action_on_server(action)
        except (httpx.TimeoutException, TimeoutError):
            raise AgentRuntimeTimeoutError("Action execution timed out")

    def get_vscode_token(self) -> str:
        if not getattr(self, "_vscode_enabled", False):
            return ""
        if not hasattr(self, "_vscode_token") or self._vscode_token is None:
            resp = self._send_action_server_request("GET", "/vscode/token")
            self._vscode_token = resp.json().get("token")
        return self._vscode_token

    def _execute_action_on_server(self, action: Any) -> Any:
        from backend.events.serialization import event_to_dict, observation_from_dict

        data = event_to_dict(action)
        resp = self._send_action_server_request("POST", "/execute", json=data)
        return observation_from_dict(resp.json())

    def _validate_action_type(self, action: Any) -> None:
        action_name = getattr(action, "action", None)
        if not action_name or not hasattr(self, action_name):
            raise ValueError(f"Action type {action_name} does not exist")

    def _send_action_server_request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{getattr(self, 'action_execution_server_url', '')}{path}"
        try:
            return send_request(None, method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.TimeoutException:
            raise TimeoutError(f"Request to action server timed out: {method} {path}")

    def _upload_file_to_runtime(self, file_handle: Any, runtime_dest: str, recursive: bool, host_src: str) -> None:
        raise UnsupportedActionError(
            "_upload_file_to_runtime is not implemented in the base "
            "ActionExecutionClient.  Use LocalRuntimeInProcess.copy_to() "
            "for in-process file transfer, or implement a subclass that "
            "uploads to the action-execution server."
        )
