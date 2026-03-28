"""Runtime creation and initialization factory.

Extracted from ``AgentSession`` to separate runtime lifecycle concerns
from session orchestration.  All functions operate on explicit parameters
rather than ``self``, making them easier to test in isolation.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from types import MappingProxyType, SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

from backend.core.errors import AgentRuntimeUnavailableError
from backend.core.bootstrap.main import _setup_runtime_and_repo
from backend.core.bootstrap.setup import initialize_repository_for_runtime
from backend.ledger.stream import EventStream
from backend.core.provider_types import (
    CustomSecretsType,
    ProviderTokenType,
    ProviderToken,
    ProviderType,
)
from backend.execution import RuntimeAcquireResult, get_runtime_cls
from backend.core.enums import RuntimeStatus
from backend.persistence.data_models.user_secrets import UserSecrets
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from logging import LoggerAdapter

    from backend.orchestration.agent import Agent
    from backend.core.config import ForgeConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.execution.base import Runtime


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_runtime(
    *,
    runtime_name: str,
    config: ForgeConfig,
    agent: Agent,
    sid: str,
    user_id: str | None,
    event_stream: EventStream,
    llm_registry: LLMRegistry,
    status_callback: Callable[..., Any] | None,
    session_logger: LoggerAdapter,
    vcs_provider_tokens: ProviderTokenType | None = None,
    custom_secrets: CustomSecretsType | None = None,
    selected_repository: str | None = None,
    selected_branch: str | None = None,
) -> RuntimeResult:
    """Create and connect a runtime, returning the result.

    Returns a :class:`RuntimeResult` with the runtime instance, acquire
    result, and repo directory.  Raises nothing — failures are reported
    through the ``RuntimeResult.success`` flag.
    """
    _ensure_no_existing_runtime(None)  # placeholder — caller should guard

    env_vars = await _prepare_runtime_env(custom_secrets, vcs_provider_tokens)
    runtime_cls = get_runtime_cls(runtime_name)
    repo_tokens = _resolve_repo_tokens(runtime_cls, vcs_provider_tokens, custom_secrets)

    session_logger.debug(
        "Initializing runtime `%s` now...",
        runtime_name,
        extra={"signal": "runtime_init_start"},
    )

    if not _can_use_shared_helper(config):
        return await _create_direct(
            runtime_cls=runtime_cls,
            config=config,
            agent=agent,
            sid=sid,
            event_stream=event_stream,
            llm_registry=llm_registry,
            status_callback=status_callback,
            session_logger=session_logger,
            repo_tokens=repo_tokens,
            env_vars=env_vars,
            selected_repository=selected_repository,
            selected_branch=selected_branch,
        )

    repo_initializer = _build_repo_initializer(
        repo_tokens, selected_repository, selected_branch
    )
    return _create_with_helper(
        config=config,
        agent=agent,
        sid=sid,
        user_id=user_id,
        event_stream=event_stream,
        llm_registry=llm_registry,
        status_callback=status_callback,
        session_logger=session_logger,
        repo_tokens=repo_tokens,
        env_vars=env_vars,
        repo_initializer=repo_initializer,
    )


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


class RuntimeResult:
    """Container for runtime creation outcome."""

    __slots__ = ("runtime", "acquire_result", "repo_directory", "success")

    def __init__(
        self,
        *,
        runtime: Runtime | None = None,
        acquire_result: RuntimeAcquireResult | None = None,
        repo_directory: str | None = None,
        success: bool = True,
    ) -> None:
        self.runtime = runtime
        self.acquire_result = acquire_result
        self.repo_directory = repo_directory
        self.success = success


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_no_existing_runtime(runtime: Runtime | None) -> None:
    if runtime is not None:
        msg = "Runtime already created"
        raise RuntimeError(msg)


async def _prepare_runtime_env(
    custom_secrets: CustomSecretsType | None,
    vcs_provider_tokens: ProviderTokenType | None,
) -> dict[str, str]:
    custom_secret_dict = dict(custom_secrets or {})
    custom_secrets_handler = UserSecrets(custom_secrets=custom_secret_dict)
    env_vars = custom_secrets_handler.get_env_vars()

    provider_tokens = (
        vcs_provider_tokens
        if isinstance(vcs_provider_tokens, MappingProxyType)
        else MappingProxyType(dict(vcs_provider_tokens or {}))
    )
    from backend.gateway.provider_handler import ProviderHandler

    provider_handler = ProviderHandler(provider_tokens=provider_tokens)
    provider_env_raw = await provider_handler.get_env_vars(expose_secrets=True)
    provider_env = cast(Mapping[str, str], provider_env_raw)
    env_vars.update(provider_env)
    return env_vars


def _resolve_repo_tokens(
    runtime_cls: type,
    vcs_provider_tokens: ProviderTokenType | None,
    custom_secrets: CustomSecretsType | None,
) -> MappingProxyType[ProviderType, ProviderToken] | None:
    if isinstance(vcs_provider_tokens, MappingProxyType):
        return vcs_provider_tokens
    return MappingProxyType(dict(vcs_provider_tokens or {}))


def _can_use_shared_helper(config: ForgeConfig) -> bool:
    return all(
        hasattr(config, attr) for attr in ("runtime", "runtime_config", "file_store")
    )


def _build_repo_initializer(
    repo_tokens: ProviderTokenType | None,
    selected_repository: str | None,
    selected_branch: str | None,
) -> Callable[[Runtime], str | None] | None:
    if not selected_repository:
        return None

    def _repo_initializer(runtime: Runtime) -> str | None:
        return initialize_repository_for_runtime(
            runtime,
            immutable_provider_tokens=repo_tokens,
            selected_repository=selected_repository,
            selected_branch=selected_branch,
        )

    return _repo_initializer


async def _create_direct(
    *,
    runtime_cls: type,
    config: ForgeConfig | SimpleNamespace,
    agent: Agent,
    sid: str,
    event_stream: EventStream,
    llm_registry: LLMRegistry,
    status_callback: Callable[..., Any] | None,
    session_logger: LoggerAdapter,
    repo_tokens: ProviderTokenType | None,
    env_vars: dict[str, str],
    selected_repository: str | None,
    selected_branch: str | None,
) -> RuntimeResult:
    from backend.core.bootstrap.setup import filter_plugins_by_config

    plugins = filter_plugins_by_config(
        plugins=list(agent.runtime_plugins),
        agent=agent,
        config=config if not isinstance(config, SimpleNamespace) else None,
        agent_cls_name=type(agent).__name__,
    )

    session_logger.debug(
        "Creating runtime instance directly: %s",
        runtime_cls.__name__,
        extra={"signal": "runtime_direct_create", "runtime": runtime_cls.__name__},
    )

    runtime = runtime_cls(
        config=config,
        event_stream=event_stream,
        llm_registry=llm_registry,
        sid=sid,
        plugins=plugins,
        status_callback=status_callback,
        headless_mode=False,
        attach_to_existing=False,
        env_vars=env_vars,
        vcs_provider_tokens=repo_tokens,
    )
    try:
        connect_start = time.time()
        session_logger.debug(
            "Connecting to runtime...", extra={"signal": "runtime_connect_start"}
        )
        await runtime.connect()
        connect_duration = time.time() - connect_start
        session_logger.info(
            "Runtime.connect() succeeded in %.2fs",
            connect_duration,
            extra={
                "signal": "runtime_connect_success",
                "duration_s": connect_duration,
            },
        )
    except AgentRuntimeUnavailableError as e:
        session_logger.exception("Runtime initialization failed: %s", e)
        if status_callback:
            status_callback("error", RuntimeStatus.ERROR_RUNTIME_DISCONNECTED, str(e))
        return RuntimeResult(success=False)

    repo_dir = await runtime.clone_or_init_repo(
        repo_tokens, selected_repository, selected_branch
    )
    await call_sync_from_async(runtime.maybe_run_setup_script)
    await call_sync_from_async(runtime.maybe_setup_git_hooks)
    repo_directory = repo_dir or (
        selected_repository.split("/")[-1] if selected_repository else None
    )
    session_logger.debug(
        "Runtime initialized with plugins: %s",
        [plugin.name for plugin in runtime.plugins],
    )
    return RuntimeResult(runtime=runtime, repo_directory=repo_directory)


def _create_with_helper(
    *,
    config: ForgeConfig,
    agent: Agent,
    sid: str,
    user_id: str | None,
    event_stream: EventStream,
    llm_registry: LLMRegistry,
    status_callback: Callable[..., Any] | None,
    session_logger: LoggerAdapter,
    repo_tokens: ProviderTokenType | None,
    env_vars: dict[str, str],
    repo_initializer: Callable[[Runtime], str | None] | None,
) -> RuntimeResult:
    try:
        session_logger.debug(
            "Setting up runtime with shared helper",
            extra={"signal": "runtime_helper_start", "sid": sid},
        )
        helper_start = time.time()
        acquire_result = _setup_runtime_and_repo(
            config,
            sid,
            llm_registry,
            agent,
            headless_mode=False,
            vcs_provider_tokens=repo_tokens,
            repo_initializer=repo_initializer,
            event_stream=event_stream,  # type: ignore[arg-type]
            env_vars=env_vars,
            user_id=user_id,
        )
        helper_duration = time.time() - helper_start
        session_logger.info(
            "_setup_runtime_and_repo completed in %.2fs",
            helper_duration,
            extra={
                "signal": "runtime_helper_success",
                "duration_s": helper_duration,
            },
        )
    except AgentRuntimeUnavailableError as e:
        session_logger.exception("Runtime initialization failed: %s", e)
        if status_callback:
            status_callback("error", RuntimeStatus.ERROR_RUNTIME_DISCONNECTED, str(e))
        return RuntimeResult(success=False)

    runtime = acquire_result.runtime
    session_logger.debug(
        "Runtime initialized with plugins: %s",
        [plugin.name for plugin in runtime.plugins],
    )
    return RuntimeResult(
        runtime=runtime,
        acquire_result=acquire_result,
        repo_directory=acquire_result.repo_directory,
    )
