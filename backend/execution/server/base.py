"""Runtime environment and execution infrastructure.

Classes:
    Runtime

Functions:
    runtime_initialized
    setup_initial_env
    close
    log
    set_runtime_status
"""

from __future__ import annotations

import asyncio
import copy
import os
import weakref
from abc import abstractmethod
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Self, cast

import httpx

from backend.core.enums import RuntimeStatus
from backend.core.errors import AgentRuntimeDisconnectedError
from backend.core.logging.logger import app_logger as logger
from backend.core.providers.provider_handler import ProviderHandler
from backend.execution.aes.policy_block_messages import action_timeout_message
from backend.execution.aes.security_enforcement import SecurityEnforcementMixin
from backend.execution.capabilities import RuntimeCapabilities
from backend.execution.playbook_loader import PlaybookLoaderMixin
from backend.execution.plugins import PluginRequirement
from backend.execution.runtime_mixins.command_timeout import CommandTimeoutMixin
from backend.execution.runtime_mixins.env_manager import EnvManagerMixin
from backend.execution.runtime_mixins.git_setup import GitSetupMixin
from backend.execution.task_tracking import TaskTrackingMixin
from backend.execution.acceptance_criteria import AcceptanceCriteriaMixin
from backend.execution.utils.git.git_handler import CommandResult, GitHandler
from backend.ledger import EventSource, EventStream, EventStreamSubscriber
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    SystemHintAction,
    TaskTrackingAction,
    AcceptanceCriteriaAction,
    is_debugger_action,
)
from backend.ledger.action.mcp import MCPAction
from backend.ledger.observation import (
    AgentThinkObservation,
    ErrorObservation,
    NullObservation,
    Observation,
)
from backend.ledger.observation_cause import attach_observation_cause
from backend.ledger.serialization.action import ACTION_TYPE_TO_CLASS
from backend.security import SecurityAnalyzer, options
from backend.utils.async_helpers.async_utils import (
    DEBUGGER_SYNC_EXECUTOR,
    GENERAL_TIMEOUT,
    call_async_from_sync,
    call_sync_from_async,
    run_or_schedule,
)

if TYPE_CHECKING:
    from pydantic import SecretStr

    from backend.core.config import AppConfig, RuntimeConfig
    from backend.core.config.mcp_config import MCPConfig
    from backend.core.providers.provider_models import (
        ProviderToken,
        ProviderTokenType,
        ProviderType,
    )
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger.event import Event
    from backend.playbooks.engine import BasePlaybook
else:
    BasePlaybook = Any


# Action types handled by the agent system, NOT the runtime.
# Defined once here to avoid duplication across run_action/validate_action.
AGENT_LEVEL_ACTIONS: frozenset[str] = frozenset(
    {
        'change_agent_state',
        'message',
        'recall',
        'think',
        'system_hint',
        'reject',
        'delegate',
        'delegate_task',
        'blackboard',
        'condensation',
        'condensation_request',
        'task_tracking',
        'acceptance_criteria',
        'uncertainty',
        'proposal',
        'clarification',
        'escalate',
        'system',
        'streaming_chunk',
    }
)


def _run_runtime_close(ref: weakref.ref[Runtime]) -> None:
    """Static finalizer callback — invoked when a Runtime is GC'd or at shutdown."""
    runtime = ref()
    if runtime is None:
        return
    try:
        runtime.close()
    except Exception:
        pass


def _default_env_vars(runtime_config: RuntimeConfig) -> dict[str, str]:
    """Build default environment variables for runtime from host environment.

    Copies environment variables prefixed with RUNTIME_ENV_ into the runtime,
    removing the prefix. Also sets auto-lint flag if enabled.

    Args:
        runtime_config: Runtime configuration settings

    Returns:
        Dictionary of environment variables for the runtime

    """
    ret = {}
    for key in os.environ:
        if key.startswith('RUNTIME_ENV_'):
            runtime_key = key.removeprefix('RUNTIME_ENV_')
            ret[runtime_key] = os.environ[key]
    if runtime_config.enable_auto_lint:
        ret['ENABLE_AUTO_LINT'] = 'true'
    return ret


def _normalize_provider_tokens(
    tokens: ProviderTokenType | None,
) -> MappingProxyType[ProviderType, ProviderToken]:
    """Ensure provider tokens are stored as an immutable mapping."""
    if isinstance(tokens, MappingProxyType):
        return tokens
    if tokens is None:
        return MappingProxyType({})
    return MappingProxyType(dict(tokens))


class Runtime(
    EnvManagerMixin,
    GitSetupMixin,
    PlaybookLoaderMixin,
    TaskTrackingMixin,
    AcceptanceCriteriaMixin,
    CommandTimeoutMixin,
    SecurityEnforcementMixin,
):
    """Abstract base class for agent runtime environments.

    This is an extension point in Grinta that allows applications to customize how
    agents interact with the external environment. The runtime provides an environment with:
    - Bash shell access
    - Browser interaction
    - Filesystem operations
    - Git operations
    - Environment variable management

    Applications can substitute their own implementation by:
    1. Creating a class that inherits from Runtime
    2. Implementing all required methods
    3. Setting the runtime name in configuration or using get_runtime_cls()

    The class is instantiated via get_impl() in get_runtime_cls().

    Built-in implementations include:
    - LocalRuntime: Local execution on the host machine (default)

    Args:
        sid: Session ID that uniquely identifies the current user session

    """

    sid: str
    config: AppConfig
    initial_env_vars: dict[str, str]
    attach_to_existing: bool
    status_callback: Callable[[str, RuntimeStatus, str], None] | None
    runtime_status: RuntimeStatus | None
    _runtime_initialized: bool = False
    security_analyzer: SecurityAnalyzer | None = None
    project_root: str | None = None
    capabilities: RuntimeCapabilities | None = None
    """Frozen capability snapshot, populated during ``connect()``."""

    def __init__(
        self,
        config: AppConfig,
        event_stream: EventStream | None,
        llm_registry: LLMRegistry,
        sid: str = 'default',
        plugins: list[PluginRequirement] | None = None,
        env_vars: dict[str, str] | None = None,
        status_callback: Callable[[str, RuntimeStatus, str], None] | None = None,
        attach_to_existing: bool = False,
        headless_mode: bool = False,
        user_id: str | None = None,
        vcs_provider_tokens: ProviderTokenType | None = None,
        project_root: str | None = None,
    ) -> None:
        """Initialize runtime state, subscriptions, plugins, and provider credentials."""
        self.git_handler = GitHandler(
            execute_shell_fn=self._execute_shell_fn_git_handler,
            create_file_fn=self._create_file_fn_git_handler,
        )
        self.sid = sid
        self.event_stream = None
        self.project_root = project_root
        self.rebind_event_stream(event_stream, sid=sid)
        self.plugins = copy.deepcopy(plugins) if plugins is not None and plugins else []
        self.status_callback = status_callback
        self.attach_to_existing = attach_to_existing
        self.config = copy.deepcopy(config)
        # Use weakref.finalize instead of atexit.register so that:
        # 1. Each runtime instance gets its own cleanup trigger.
        # 2. When the runtime is GC'd, the finalizer fires.
        # 3. During interpreter shutdown, pending finalizers still run.
        # 4. Old instances that have been GC'd don't leave stale atexit handlers
        #    that could clean up resources owned by newer instances.
        self._finalizer = weakref.finalize(self, _run_runtime_close, weakref.ref(self))
        self.initial_env_vars = _default_env_vars(config.runtime_config)
        if env_vars is not None:
            self.initial_env_vars.update(env_vars)
        provider_tokens = _normalize_provider_tokens(vcs_provider_tokens)
        self.provider_handler = ProviderHandler(
            provider_tokens=provider_tokens,
        )
        raw_env_vars = cast(
            dict[str, str],
            call_async_from_sync(
                self.provider_handler.get_env_vars,
                GENERAL_TIMEOUT,
                True,
            ),
        )
        self.initial_env_vars.update(raw_env_vars)
        self.user_id = user_id
        self.vcs_provider_tokens = provider_tokens

        # 🧹 CRITICAL FIX: Process manager for tracking and cleaning up long-running processes
        from backend.execution.utils.process.process_manager import ProcessManager

        self.process_manager = ProcessManager()
        self.runtime_status = None
        self.security_analyzer = None
        if self.config.security.security_analyzer:
            # SecurityAnalyzers is a dict-like object in options module
            analyzer_cls = getattr(options, 'SecurityAnalyzers', {}).get(  # type: ignore[attr-defined]
                self.config.security.security_analyzer, SecurityAnalyzer
            )
            self.security_analyzer = analyzer_cls()
            logger.debug(
                'Security analyzer %s initialized for runtime %s',
                analyzer_cls.__name__,
                self.sid,
            )

    def rebind_event_stream(
        self, event_stream: EventStream | None, sid: str | None = None
    ) -> None:
        """Rebind runtime event subscription when the runtime is reused.

        Warm-pooled runtimes can outlive a conversation. When reattached to a new
        session, they must unsubscribe from the old stream and subscribe to the new
        one, otherwise actions are emitted but never executed by the runtime.
        """
        old_stream = getattr(self, 'event_stream', None)
        old_sid = getattr(self, 'sid', None)

        if old_stream is not None and old_sid is not None:
            try:
                old_stream.unsubscribe(EventStreamSubscriber.RUNTIME, old_sid)
            except Exception:
                pass

        if sid is not None:
            self.sid = sid

        self.event_stream = event_stream
        if self.event_stream is None:
            return

        try:
            self.event_stream.unsubscribe(EventStreamSubscriber.RUNTIME, self.sid)
        except Exception:
            pass

        self.event_stream.subscribe(
            EventStreamSubscriber.RUNTIME,
            self.on_event,
            self.sid,
        )

    @property
    def workspace_root(self) -> Path:
        """Absolute path to the active workspace directory.

        Subclasses (e.g. LocalRuntimeInProcess) override this to expose their
        internal workspace tracking attribute.  The base implementation falls
        back to ``project_root`` when set, and ``Path.cwd()`` otherwise so
        that every call-site can rely on a single, always-valid property.
        """
        if self.project_root:
            return Path(self.project_root)
        return Path.cwd()

    @workspace_root.setter
    def workspace_root(self, value: Path) -> None:
        self.project_root = str(value)

    @property
    def runtime_initialized(self) -> bool:
        """Check if runtime has completed initialization.

        Returns:
            True if runtime is initialized and ready

        """
        return self._runtime_initialized

    def setup_initial_env(self) -> None:
        """Set up initial environment variables and git configuration.

        Skipped if attaching to existing runtime. Adds initial env vars,
        runtime startup vars, and configures git user settings.
        """
        if self.attach_to_existing:
            return
        logger.debug('Adding env vars: %s', self.initial_env_vars.keys())
        self.add_env_vars(self.initial_env_vars)
        if self.config.runtime_config.runtime_startup_env_vars:
            self.add_env_vars(self.config.runtime_config.runtime_startup_env_vars)
        self._setup_git_config()

    def close(self) -> None:
        """This should only be called by conversation manager or closing the session.

        If called for instance by error handling, it could prevent recovery.
        """
        self._runtime_initialized = False
        if not self._should_cleanup_processes():
            return
        try:
            logger.info(
                '🧹 Cleaning up %s long-running processes',
                self.process_manager.count(),
            )
            self._cleanup_processes()
        except Exception as e:
            logger.error('Failed to cleanup processes: %s', e)

    def _should_cleanup_processes(self) -> bool:
        return hasattr(self, 'process_manager') and self.process_manager.count() > 0

    def _cleanup_processes(self) -> None:
        loop, created = self._resolve_event_loop()
        if loop and loop.is_running():
            from backend.utils.async_helpers.async_utils import create_tracked_task

            create_tracked_task(
                self.process_manager.cleanup_all(runtime=self),
                name='process-cleanup',
            )
            return
        self._run_cleanup_synchronously(loop, created)

    def _resolve_event_loop(self) -> tuple[asyncio.AbstractEventLoop | None, bool]:
        try:
            loop = asyncio.get_running_loop()
            return loop, False
        except RuntimeError:
            pass
        try:
            loop = asyncio.get_event_loop()
            return loop, False
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop, True

    def _run_cleanup_synchronously(
        self, loop: asyncio.AbstractEventLoop | None, created: bool
    ) -> None:
        if loop is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            created = True
        try:
            loop.run_until_complete(self.process_manager.cleanup_all(runtime=self))
        finally:
            self._close_loop_if_needed(loop, created)

    def _close_loop_if_needed(
        self, loop: asyncio.AbstractEventLoop, created: bool
    ) -> None:
        if not created:
            return
        try:
            if loop and not loop.is_closed() and loop is not asyncio.get_running_loop():
                loop.close()
        except RuntimeError:
            pass

    @classmethod
    async def delete(cls, conversation_id: str) -> None:
        """Delete runtime resources associated with a conversation.

        Args:
            conversation_id: ID of conversation to clean up

        """

    def log(self, level: str, message: str) -> None:
        """Log message with runtime context.

        Args:
            level: Log level ('debug', 'info', 'warning', 'error')
            message: Message to log

        """
        message = f'[runtime {self.sid}] {message}'
        getattr(logger, level)(message, stacklevel=2)

    def _agent_debugger_enabled(self) -> bool:
        """Whether agent config enables the interactive DAP debugger tool."""
        from backend.core.config.app_config import AppConfig

        from backend.core.constants import DEFAULT_AGENT_DEBUGGER_ENABLED

        cfg = self.config
        if isinstance(cfg, AppConfig):
            return bool(cfg.get_agent_config(cfg.default_agent).enable_debugger)
        # Tests may pass a slim stub; fall back to code default when unspecified.
        return bool(getattr(cfg, 'enable_debugger', DEFAULT_AGENT_DEBUGGER_ENABLED))  # type: ignore[unreachable]

    def set_runtime_status(
        self, runtime_status: RuntimeStatus, msg: str = '', level: str = 'info'
    ) -> None:
        """Sends a status message if the callback function was provided."""
        self.runtime_status = runtime_status
        if self.status_callback:
            self.status_callback(level, runtime_status, msg)

    def on_event(self, event: Event) -> None:
        """Handle incoming events (primarily actions from agent).

        Args:
            event: Event to process

        """
        if isinstance(event, Action):
            action_type = type(event).__name__
            action_id = getattr(event, 'id', '?')
            logger.info(
                '[runtime %s] on_event received %s (id=%s), dispatching via run_or_schedule',
                self.sid,
                action_type,
                action_id,
            )
            run_or_schedule(self._handle_action(event))

    async def _export_latest_git_provider_tokens(self, event: Action) -> None:
        """Refresh runtime provider tokens when agent attemps to run action with provider token."""
        providers_called = ProviderHandler.check_cmd_action_for_provider_token_ref(
            event
        )
        if not providers_called:
            return
        provider_handler = ProviderHandler(
            provider_tokens=self.vcs_provider_tokens,
        )
        logger.info('Fetching latest provider tokens for runtime')
        env_vars = cast(
            'dict[ProviderType, SecretStr]',
            await provider_handler.get_env_vars(
                expose_secrets=False,
            ),
        )
        if not env_vars:
            return
        try:
            if self.event_stream:
                await provider_handler.set_event_stream_secrets(
                    self.event_stream, env_vars=env_vars
                )
            self.add_env_vars(provider_handler.expose_env_vars(env_vars))
        except Exception:
            logger.warning('Failed to export latest provider tokens to runtime')

    async def _execute_action(self, event: Action) -> Observation:
        """Execute action and return observation.

        Args:
            event: Action to execute

        Returns:
            Observation from action execution

        """
        await self._export_latest_git_provider_tokens(event)

        if isinstance(event, MCPAction):
            # MCP actions are always forwarded to the driver; the
            # ActionExecutionServer already handles Windows stdio filtering
            # and returns a graceful ErrorObservation when no servers are
            # connected.
            return await self.call_tool_mcp(event)
        # ``call_sync_from_async`` schedules ``run_action`` on the asyncio loop's
        # *default* executor. Under load those workers can sit queued behind other
        # sync actions while the controller already logged ``_handle_action START
        # DebuggerAction`` — producing multi‑minute gaps with no ``DEBUGGER_DISPATCH``.
        # Routing through ``EXECUTOR`` alone still queued debugger work behind heavy
        # ``call_async_from_sync`` bridge traffic; use ``DEBUGGER_SYNC_EXECUTOR``.
        if is_debugger_action(event):
            if not self._agent_debugger_enabled():
                return ErrorObservation(
                    content=(
                        'Interactive debugger is disabled for this session '
                        '(enable_debugger is false in agent config). '
                        'Set enable_debugger=true on the agent to use the DAP debugger tool.'
                    )
                )
            loop = asyncio.get_running_loop()
            logger.warning(
                '[DEBUGGER_BRIDGE] scheduling run_action on DEBUGGER_SYNC_EXECUTOR '
                '(action id=%s, type=%s)',
                getattr(event, 'id', '?'),
                type(event).__name__,
                extra={
                    'msg_type': 'DEBUGGER_RUN_ACTION_SCHEDULED',
                    'action_id': getattr(event, 'id', None),
                },
            )
            return await loop.run_in_executor(
                DEBUGGER_SYNC_EXECUTOR, self.run_action, event
            )
        return await call_sync_from_async(self.run_action, event)

    def _handle_runtime_error(
        self, event: Action, error: Exception, is_network_error: bool = False
    ) -> None:
        """Handle runtime error during action execution.

        Args:
            event: Action that caused error
            error: Exception raised
            is_network_error: Whether this is a network/disconnection error

        """
        runtime_status = (
            RuntimeStatus.ERROR_RUNTIME_DISCONNECTED
            if is_network_error
            else RuntimeStatus.ERROR
        )
        error_message = f'{type(error).__name__}: {error!s}'
        self.log('error', f'Unexpected error while running action: {error_message}')
        self.log('error', f'Problematic action: {event!s}')
        self.set_runtime_status(runtime_status, error_message, level='error')

    def _process_observation(self, observation: Observation, event: Action) -> bool:
        """Process observation result and add to event stream.

        Args:
            observation: Observation to process
            event: Source action

        Returns:
            True if observation should be added to stream, False otherwise

        """
        attach_observation_cause(
            observation, event, context='runtime._process_observation'
        )
        observation.tool_call_metadata = event.tool_call_metadata

        # Attach a structured result payload for downstream consumers.
        # This avoids fragile parsing of free-form observation content.
        try:
            exit_code: int | None = getattr(observation, 'exit_code', None)
        except Exception:
            exit_code = None

        existing_tool_result = (
            observation.tool_result if isinstance(observation.tool_result, dict) else {}
        )
        observation.tool_result = {
            **existing_tool_result,
            'ok': existing_tool_result.get(
                'ok', not isinstance(observation, ErrorObservation)
            ),
            'retryable': existing_tool_result.get(
                'retryable', isinstance(observation, ErrorObservation)
            ),
            'exit_code': existing_tool_result.get('exit_code', exit_code),
            'action': existing_tool_result.get(
                'action', getattr(event, 'action', None)
            ),
            'observation': existing_tool_result.get(
                'observation', getattr(observation, 'observation', None)
            ),
        }

        if isinstance(observation, NullObservation):
            return False

        return True

    async def _handle_action(self, event: Action) -> None:
        """Handle action execution with timeout, error handling, and observation processing."""
        action_type = type(event).__name__
        action_id = getattr(event, 'id', '?')
        logger.debug(
            '[runtime %s] _handle_action START %s (id=%s)',
            self.sid,
            action_type,
            action_id,
        )
        self._set_action_timeout(event)
        assert event.timeout is not None, (
            f'Action {action_type} (id={action_id}) has no timeout after _set_action_timeout'
        )

        observation = await self._execute_with_timeout(event, action_type, action_id)
        if observation is None:
            return

        if not self._process_observation(observation, event):
            return
        source = event.source or EventSource.AGENT
        if self.event_stream:
            self.event_stream.add_event(observation, source)

    async def _execute_with_timeout(
        self, event: Action, action_type: str, action_id: str
    ) -> Observation | None:
        try:
            observation = await asyncio.wait_for(
                self._execute_action(event), timeout=event.timeout
            )
            logger.debug(
                '[runtime %s] _handle_action GOT observation %s for %s (id=%s)',
                self.sid,
                type(observation).__name__,
                action_type,
                action_id,
            )
            return observation
        except asyncio.TimeoutError:
            return self._handle_timeout(event, action_type, action_id)
        except PermissionError as e:
            return ErrorObservation(content=str(e))
        except ValueError as e:
            return self._handle_value_error(event, e, action_type, action_id)
        except (httpx.NetworkError, AgentRuntimeDisconnectedError) as e:
            return self._handle_network_error(event, e, action_type, action_id)
        except Exception as e:
            return self._handle_unexpected_error(event, e, action_type, action_id)

    def _handle_timeout(
        self, event: Action, action_type: str, action_id: str
    ) -> Observation | None:
        logger.warning(
            '[runtime %s] _handle_action TIMEOUT for %s (id=%s) after %.1fs',
            self.sid,
            action_type,
            action_id,
            event.timeout,
        )
        observation = ErrorObservation(
            content=action_timeout_message(timeout_seconds=event.timeout or 0.0),
            error_id='ACTION_EXECUTION_TIMEOUT',
            timeout_kind='action_execution_timeout',
        )
        if not self._process_observation(observation, event):
            return None
        if self.event_stream:
            self.event_stream.add_event(observation, event.source or EventSource.AGENT)
        return None

    def _handle_value_error(
        self, event: Action, e: ValueError, action_type: str, action_id: str
    ) -> ErrorObservation:
        from backend.core.workspace_resolution import (
            WORKSPACE_NOT_OPEN_ERROR_ID,
            is_workspace_not_open_error,
        )

        if is_workspace_not_open_error(e):
            return ErrorObservation(
                content=str(e), error_id=WORKSPACE_NOT_OPEN_ERROR_ID
            )
        self._handle_runtime_error(event, e, is_network_error=False)
        logger.warning(
            '[runtime %s] _handle_action EXCEPTION for %s (id=%s): %s: %s',
            self.sid,
            action_type,
            action_id,
            type(e).__name__,
            e,
        )
        return ErrorObservation(
            content=f'Unexpected error during action execution: {type(e).__name__}: {e}'
        )

    def _handle_network_error(
        self, event: Action, e: Exception, action_type: str, action_id: str
    ) -> ErrorObservation:
        self._handle_runtime_error(event, e, is_network_error=True)
        logger.warning(
            '[runtime %s] _handle_action RUNTIME ERROR for %s (id=%s): %s',
            self.sid,
            action_type,
            action_id,
            e,
        )
        return ErrorObservation(
            content=f'Runtime error during action execution: {type(e).__name__}: {e}'
        )

    def _handle_unexpected_error(
        self, event: Action, e: Exception, action_type: str, action_id: str
    ) -> ErrorObservation:
        self._handle_runtime_error(event, e, is_network_error=False)
        logger.warning(
            '[runtime %s] _handle_action EXCEPTION for %s (id=%s): %s: %s',
            self.sid,
            action_type,
            action_id,
            type(e).__name__,
            e,
        )
        return ErrorObservation(
            content=f'Unexpected error during action execution: {type(e).__name__}: {e}'
        )

    def run_action(self, action: Action) -> Observation:
        """Run an action and return the resulting observation."""
        special = self._handle_special_actions(action)
        if special is not None:
            return special

        confirmation_result = self._check_action_confirmation(action)
        if confirmation_result is not None:
            return confirmation_result

        enforcement_result = self._enforce_security(action)
        if enforcement_result is not None:
            return enforcement_result

        validation_result = self._validate_action(action)
        if validation_result is not None:
            return validation_result

        if action.action in AGENT_LEVEL_ACTIONS:
            return NullObservation(content='')

        observation = self._execute_action_sync(action)
        if hasattr(action, 'truncation_strategy') and getattr(
            action, 'truncation_strategy'
        ):
            observation.truncation_strategy = getattr(action, 'truncation_strategy')

        verification_obs = self._verify_action_if_needed(action, observation)
        if verification_obs:
            return verification_obs

        if hasattr(action, 'truncation_strategy') and getattr(
            action, 'truncation_strategy'
        ):
            observation.truncation_strategy = getattr(action, 'truncation_strategy')
        return observation

    def _handle_special_actions(self, action: Action) -> Observation | None:
        if isinstance(action, AgentThinkAction):
            return self._make_think_observation(action)
        if isinstance(action, SystemHintAction):
            return self._make_system_hint_observation(action)
        if isinstance(action, TaskTrackingAction):
            return self._handle_task_tracking_action(action)
        if isinstance(action, AcceptanceCriteriaAction):
            return self._handle_acceptance_criteria_action(action)
        if is_debugger_action(action):
            return self._handle_debugger_action(action)
        return None

    def _make_system_hint_observation(
        self, action: SystemHintAction
    ) -> NullObservation:
        return NullObservation(content='')

    def _make_think_observation(
        self, action: AgentThinkAction
    ) -> AgentThinkObservation:
        observation = AgentThinkObservation(
            'Your thought has been logged.',
            suppress_cli=getattr(action, 'suppress_cli', False)
            or bool(getattr(action, 'source_tool', '')),
        )
        tool_result = getattr(action, 'tool_result', None)
        if isinstance(tool_result, dict):
            observation.tool_result = dict(tool_result)
        return observation

    def _handle_debugger_action(self, action: Action) -> ErrorObservation | None:
        if not self._agent_debugger_enabled():
            return ErrorObservation(
                content='Interactive debugger is disabled for this session (enable_debugger is false in agent config). Set enable_debugger=true on the agent to use the DAP debugger tool.'
            )
        logger.warning(
            '[DEBUGGER_BRIDGE] run_action entered on worker thread (action id=%s)',
            getattr(action, 'id', '?'),
            extra={
                'msg_type': 'DEBUGGER_RUN_ACTION_ENTER',
                'action_id': getattr(action, 'id', None),
            },
        )
        return None

    def _verify_action_if_needed(
        self, action: Action, observation: Observation
    ) -> Observation | None:
        """Verify critical actions to prevent hallucinations (Layer 3)."""
        if not isinstance(action, FileEditAction):
            return None
        if isinstance(observation, ErrorObservation):
            return None

        try:
            file_path = action.path
            if not file_path or file_path == '.':
                return None
            file_on_disk = self._resolve_verification_path(file_path)
            if not file_on_disk.is_file():
                return self._make_verification_failure_observation(
                    file_path, observation
                )
            return self._enhance_observation_with_line_count(
                observation, file_path, file_on_disk
            )
        except Exception as e:
            logger.warning('Verification error for %s: %s', action.path, e)
            return None

    def _resolve_verification_path(self, file_path: str) -> Path:
        normalized = file_path.lstrip('/\\')
        if normalized.startswith('workspace/') or normalized.startswith('workspace\\'):
            normalized = normalized[len('workspace/') :]
        elif normalized == 'workspace':
            normalized = '.'
        file_on_disk = Path(normalized)
        if not file_on_disk.is_absolute():
            file_on_disk = self.workspace_root / file_on_disk
        return file_on_disk

    def _make_verification_failure_observation(
        self, file_path: str, observation: Observation
    ) -> ErrorObservation:
        from backend.core.errors.structured_edit_errors import (
            build_verification_failure_tool_result,
            format_verification_failure_message,
        )

        logger.error(
            'VERIFICATION FAILURE: File %s missing after file operation', file_path
        )
        _ = observation
        error_msg = format_verification_failure_message(file_path)
        err = ErrorObservation(content=error_msg)
        err.tool_result = build_verification_failure_tool_result(file_path)
        return err

    def _enhance_observation_with_line_count(
        self, observation: Observation, file_path: str, file_on_disk: Path
    ) -> Observation | None:
        """Append a line-count footer to *observation* without changing its type."""
        try:
            with file_on_disk.open('r', encoding='utf-8', errors='replace') as f:
                line_count = sum(1 for _ in f)
        except OSError:
            line_count = None
        if line_count is None:
            return None
        footer = f'\n\nFile written: {file_path} ({line_count} lines)'
        current = str(getattr(observation, 'content', '') or '')
        if footer not in current:
            observation.content = f'{current}{footer}'
        return observation

    def _validate_action(self, action: Action) -> Observation | None:
        """Validate action type and runtime support."""
        action_type = action.action

        if action_type not in ACTION_TYPE_TO_CLASS:
            return ErrorObservation(f'Action {action_type} does not exist.')

        # Agent-level actions that should not be executed by runtime
        if action_type in AGENT_LEVEL_ACTIONS:
            # These actions are handled by the agent system, not the runtime
            return None

        if not hasattr(self, action_type):
            return ErrorObservation(
                f'Action {action_type} is not supported in the current runtime.'
            )

        return None

    def _execute_action_sync(self, action: Action) -> Observation:
        """Execute the validated action (synchronous internal path)."""
        action_type = action.action
        return getattr(self, action_type)(action)

    def __enter__(self) -> Self:
        """Enter runtime context manager.

        Returns:
            Self for context manager protocol

        """
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Exit runtime context manager, ensuring cleanup.

        Args:
            exc_type: Exception type if an error occurred
            exc_value: Exception value if an error occurred
            traceback: Traceback if an error occurred

        """
        self.close()

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the runtime environment.

        Must be implemented by subclasses to establish connection to
        the execution environment (local process, subprocess, etc.).
        """

    @abstractmethod
    def get_mcp_config(self, extra_servers: list[Any] | None = None) -> MCPConfig:
        """Get MCP configuration for this runtime."""

    @abstractmethod
    def run(self, action: CmdRunAction) -> Observation:
        """Execute a bash/shell command in the runtime environment."""

    @abstractmethod
    def read(self, action: FileReadAction) -> Observation:
        """Read file contents from the runtime filesystem."""

    @abstractmethod
    def edit(self, action: FileEditAction) -> Observation:
        """Edit file using search/replace or other edit operations."""

    @abstractmethod
    def copy_to(
        self, host_src: str, runtime_dest: str, recursive: bool = False
    ) -> None:
        """Copy files from host into the runtime environment."""
        raise NotImplementedError

    @abstractmethod
    def copy_from(self, path: str) -> Path:
        """Copy files from the runtime environment to the host."""
        raise NotImplementedError

    @abstractmethod
    def list_files(self, path: str, recursive: bool = False) -> list[str]:
        """List files within the runtime environment."""
        raise NotImplementedError

    @abstractmethod
    async def call_tool_mcp(self, action: MCPAction) -> Observation:
        """Call an MCP (Model Context Protocol) tool.

        Args:
            action: MCP action with tool name and arguments

        Returns:
            Observation with tool execution results

        """

    def get_git_diff(self, file_path: str, cwd: str) -> dict[str, str]:
        """Get git diff for a specific file.

        Args:
            file_path: Path to file to diff
            cwd: Working directory for git command

        Returns:
            Dictionary with diff information

        """
        self.git_handler.set_cwd(cwd)
        return self.git_handler.get_git_diff(file_path)

    def get_workspace_branch(self, primary_repo_path: str | None = None) -> str | None:
        """Get the current branch of the workspace.

        Args:
            primary_repo_path: Path to the primary repository within the workspace.
                              If None, uses the workspace root.

        Returns:
            str | None: The current branch name, or None if not a git repository or error occurs.

        """
        if primary_repo_path:
            git_cwd = str(self.workspace_root / primary_repo_path)
        else:
            git_cwd = str(self.workspace_root)
        self.git_handler.set_cwd(git_cwd)
        return self.git_handler.get_current_branch()

    def _execute_shell_fn_git_handler(
        self, command: str, cwd: str | None
    ) -> CommandResult:
        """This function is used by the GitHandler to execute shell commands."""
        obs = self.run(
            CmdRunAction(command=command, is_static=True, hidden=True, cwd=cwd)
        )
        exit_code = 0
        if isinstance(obs, ErrorObservation):
            exit_code = -1
        else:
            exit_attr = getattr(obs, 'exit_code', None)
            if isinstance(exit_attr, int):
                exit_code = exit_attr
        content = getattr(obs, 'content', '')
        return CommandResult(content=content, exit_code=exit_code)

    def _create_file_fn_git_handler(self, path: str, content: str) -> int:
        """This function is used by the GitHandler to create files in the runtime."""
        obs = self.edit(
            FileEditAction(path=path, command='create_file', file_text=content)
        )
        return -1 if isinstance(obs, ErrorObservation) else 0

    def additional_agent_instructions(self) -> str:
        """Provide runtime-specific instructions appended to agent prompts."""
        return ''

    def subscribe_to_shell_stream(
        self, callback: Callable[[str], None] | None = None
    ) -> bool:
        """Subscribe to shell command output stream.

        This method is meant to be overridden by runtime implementations
        that want to stream shell command output to external consumers.

        Args:
            callback: A function that will be called with each line of output from shell commands.
                     If None, any existing subscription will be removed.

        Returns False by default.

        """
        return False

    @classmethod
    def setup(cls, config: AppConfig, headless_mode: bool = False) -> None:
        """Set up the environment for runtimes to be created."""

    @classmethod
    def teardown(cls, config: AppConfig) -> None:
        """Tear down the environment in which runtimes are created."""
