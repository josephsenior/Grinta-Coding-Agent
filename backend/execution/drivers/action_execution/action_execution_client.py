from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import httpx

from backend.execution.server.base import Runtime
from backend.execution.utils.files.request import send_request
from backend.execution.utils.system_stats import update_last_execution_time
from backend.utils.http.http_session import HttpSession

if TYPE_CHECKING:
    from backend.core.config import AppConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger import EventStream


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
    * *Platform-restricted* — remote-only behaviors may differ when a local MCP
      configuration is present.  ``call_tool_mcp`` and ``get_mcp_config`` use
      the shared MCP runtime on all platforms.
    * *Not yet implemented* — calling raises ``UnsupportedActionError`` with a
    human-readable message (``copy_from``, ``_upload_file_to_runtime``).

    Subclasses (e.g. ``LocalRuntimeInProcess``) may override any method to
    provide a concrete implementation without changing this contract.
    """

    # Actions that are always dispatched to the server
    _SERVER_ACTIONS: frozenset[str] = frozenset(
        {
            'run',
            'terminal_run',
            'terminal_input',
            'terminal_read',
            'terminal_wait',
            'terminal_list',
            'terminal_close',
            'debugger',
            'read',
            'edit',
            'think',
            'null',
            'finish_playbook',
        }
    )

    # Actions that require a remote action-execution server endpoint
    _REMOTE_ONLY_ACTIONS: frozenset[str] = frozenset()

    def __init__(
        self,
        config: AppConfig,
        event_stream: EventStream | None,
        llm_registry: LLMRegistry,
        sid: str = 'default',
        plugins: list[Any] | None = None,
        env_vars: dict[str, str] | None = None,
        status_callback: Any | None = None,
        attach_to_existing: bool = False,
        headless_mode: bool = False,
        user_id: str | None = None,
        vcs_provider_tokens: Any | None = None,
        project_root: str | None = None,
        *args: object,
        **kwargs: object,
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
            project_root=project_root,
        )
        self._vscode_token: str | None = None
        self._action_server_session = HttpSession()
        self._mcp_clients: list[Any] | None = None
        self._mcp_servers_resolved: list[Any] | None = None
        self._mcp_config: Any | None = getattr(config, 'mcp', None)

    async def connect(self) -> None:
        pass

    def get_mcp_config(self, extra_servers: list[Any] | None = None) -> Any:
        from backend.core.config.mcp_config import (
            MCPConfig,
            MCPServerConfig,
            _filter_windows_stdio_servers,
        )

        local_cfg = getattr(self.config, 'mcp', None)
        servers = list(getattr(local_cfg, 'servers', []) or []) if local_cfg else []

        server_url = (getattr(self, 'action_execution_server_url', None) or '').strip()
        if server_url:
            try:
                resp = self._send_action_server_request('GET', '/mcp_config')
                data = resp.json()
                remote = [MCPServerConfig(**s) for s in data.get('servers', [])]
                if remote:
                    servers = remote
            except Exception as exc:
                logger.debug(
                    'Remote MCP config unavailable; using local configuration: %s',
                    exc,
                )

        servers = _filter_windows_stdio_servers(list(servers))
        config = MCPConfig(servers=servers)

        if not config.servers and server_url:
            config.servers.append(
                MCPServerConfig(
                    name='default',
                    type='sse',
                    url=f'{server_url.rstrip("/")}/mcp',
                    transport='sse',
                )
            )

        if extra_servers:
            config.servers.extend(extra_servers)
            if server_url:
                try:
                    self._send_action_server_request(
                        'POST',
                        '/mcp_config',
                        json={'servers': [s.model_dump() for s in config.servers]},
                    )
                    self._last_updated_mcp_stdio_servers = extra_servers
                except Exception as exc:
                    logger.debug('Failed to push MCP config to remote server: %s', exc)

        return config

    def run(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def read(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def edit(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def terminal_run(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def terminal_input(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def terminal_read(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def terminal_wait(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def terminal_list(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def debugger(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def copy_to(
        self, host_src: str, runtime_dest: str, recursive: bool = False
    ) -> None:
        import os
        import tempfile
        from zipfile import ZipFile

        if not os.path.exists(host_src):
            raise FileNotFoundError(f'Source path {host_src} does not exist')

        if recursive:
            fd, tmp_path = tempfile.mkstemp(suffix='.zip')
            os.close(fd)
            try:
                with ZipFile(tmp_path, 'w') as zipf:
                    for root, _, files in os.walk(host_src):
                        for file in files:
                            full_path = os.path.join(root, file)
                            arcname = os.path.relpath(full_path, host_src)
                            zipf.write(full_path, arcname)

                with open(tmp_path, 'rb') as f:
                    self._upload_file_to_runtime(f, runtime_dest, recursive, host_src)
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        else:
            with open(host_src, 'rb') as f:
                self._upload_file_to_runtime(f, runtime_dest, recursive, host_src)

    def copy_from(self, path: str) -> Any:
        raise UnsupportedActionError(
            'copy_from is not implemented in ActionExecutionClient. '
            'Override in a subclass (e.g. LocalRuntimeInProcess) to provide '
            'runtime-to-host file transfer.'
        )

    def list_files(self, path: str | None = None, recursive: bool = False) -> list[str]:
        resp = self._send_action_server_request(
            'GET', '/list_files', params={'path': path, 'recursive': recursive}
        )
        return resp.json()

    async def call_tool_mcp(self, action: Any) -> Any:
        """Execute an MCP tool call using the shared runtime MCP integration."""
        from backend.execution.utils.mcp_runtime import call_mcp_action

        observation, clients, servers = await call_mcp_action(
            action,
            mcp_config=self._mcp_config or getattr(self.config, 'mcp', None),
            clients=self._mcp_clients,
            servers_resolved=self._mcp_servers_resolved,
        )
        self._mcp_clients = clients
        self._mcp_servers_resolved = servers
        return observation

    async def reload_mcp(self) -> dict[str, list[str]]:
        """Reconcile live MCP clients against the current ``AppConfig``.

        Subscribes the bus to the next emission, then reads the latest
        ``self.config.mcp`` and reuses :func:`reload_mcp_servers` to
        diff against the currently-cached client pool. Updates the
        cached pool in place. Returns a summary dict so the caller can
        surface what changed in the TUI.

        The function is a no-op (with an empty summary) when there is
        no cached client pool and the new config also has no servers,
        or when called before the first MCP call.
        """
        from backend.execution.utils.mcp_runtime import reload_mcp_servers

        new_cfg = getattr(self.config, 'mcp', None)
        new_servers = list(getattr(new_cfg, 'servers', []) or [])
        reserved = getattr(new_cfg, 'mcp_exposed_name_reserved', None) or frozenset()

        clients, servers, summary = await reload_mcp_servers(
            new_servers=new_servers,
            current_clients=self._mcp_clients,
            current_servers_resolved=self._mcp_servers_resolved,
            reserved_tool_names=frozenset(reserved),
        )
        self._mcp_clients = clients
        self._mcp_servers_resolved = servers
        return summary

    async def close_mcp(self) -> None:
        """Disconnect every cached MCP client without tearing the runtime down."""
        clients = self._mcp_clients or []
        for client in clients:
            try:
                await client.disconnect()
            except Exception as exc:
                logger.debug('MCP client disconnect: %s', exc, exc_info=True)
        self._mcp_clients = None
        self._mcp_servers_resolved = None

    def check_if_alive(self) -> None:
        self._send_action_server_request('GET', '/ping')

    def think(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def null(self, action: Any) -> Any:
        return None

    def finish_playbook(self, action: Any) -> Any:
        return self._execute_action_on_server(action)

    def send_action_for_execution(self, action: Any) -> Any:
        from backend.core.errors import AgentRuntimeTimeoutError

        try:
            self._validate_action_type(action)
        except ValueError as e:
            from backend.ledger.observation import ErrorObservation

            return ErrorObservation(content=str(e))

        if not getattr(action, 'runnable', True):
            from backend.ledger.observation import NullObservation

            return NullObservation(content='')

        update_last_execution_time()
        try:
            return self._execute_action_on_server(action)
        except (httpx.TimeoutException, TimeoutError) as err:
            raise AgentRuntimeTimeoutError('Action execution timed out') from err

    def get_vscode_token(self) -> str:
        if not getattr(self, '_vscode_enabled', False):
            return ''
        if not hasattr(self, '_vscode_token') or self._vscode_token is None:
            resp = self._send_action_server_request('GET', '/vscode/token')
            token = resp.json().get('token')
            self._vscode_token = token if isinstance(token, str) else ''
        return self._vscode_token

    def _execute_action_on_server(self, action: Any) -> Any:
        from backend.ledger.serialization import event_to_dict, observation_from_dict

        data = event_to_dict(action)
        resp = self._send_action_server_request('POST', '/execute_action', json=data)
        return observation_from_dict(resp.json())

    def _validate_action_type(self, action: Any) -> None:
        action_name = getattr(action, 'action', None)
        if not action_name or not hasattr(self, action_name):
            raise ValueError(f'Action type {action_name} does not exist')

    def _send_action_server_request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        url = f'{getattr(self, "action_execution_server_url", "")}{path}'
        try:
            return send_request(self._action_server_session, method, url, **kwargs)
        except httpx.TimeoutException as err:
            raise TimeoutError(
                f'Request to action server timed out: {method} {path}'
            ) from err

    def _upload_file_to_runtime(
        self, file_handle: Any, runtime_dest: str, recursive: bool, host_src: str
    ) -> None:
        raise UnsupportedActionError(
            '_upload_file_to_runtime is not implemented in the base '
            'ActionExecutionClient.  Use LocalRuntimeInProcess.copy_to() '
            'for in-process file transfer, or implement a subclass that '
            'uploads to the action-execution server.'
        )
