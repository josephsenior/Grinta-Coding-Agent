from __future__ import annotations

from typing import Any


def create_runtime_with_registry(config: Any, workspace_base: str | None = None):
    from backend.core.setup import create_runtime
    from backend.llm.llm_registry import LLMRegistry

    llm_registry = LLMRegistry(config)
    return create_runtime(
        config, llm_registry=llm_registry, workspace_base=workspace_base
    )


def create_safety_test_config():
    """Create a standard ForgeConfig with safety features enabled for testing."""
    import os

    from backend.core.config.agent_config import AgentConfig
    from backend.core.config.llm_config import LLMConfig
    from backend.core.config.main_config import ForgeConfig
    from backend.security.safety_config import SafetyConfig

    config = ForgeConfig()
    config.agent = AgentConfig(
        safety=SafetyConfig(
            enable_mandatory_validation=True,
            environment="development",
            block_in_production=True,
        ),
        enable_completion_validation=True,
        enable_circuit_breaker=True,
    )
    config.llm = LLMConfig(
        model="claude-sonnet-4-20250514",
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.0,
    )
    return config


async def run_task(config: Any, runtime: Any, task: str):
    from backend.core.main import run_controller
    from backend.events.action import MessageAction

    state = await run_controller(
        config_=config,
        initial_action=MessageAction(content=task, wait_for_response=False),
        runtime=runtime,
        session_id=runtime.sid,
    )
    if state is None:
        raise RuntimeError("Controller did not return state")
    return state
