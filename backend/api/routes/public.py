"""Public routes exposing available models, agents, and server metadata."""

from typing import Any

from fastapi import APIRouter

# Import engines to register all agents
from backend.controller.agent import Agent
from backend.llm.model_catalog import get_supported_llm_models
from backend.security.options import SecurityAnalyzers
from backend.api.dependencies import get_dependencies
from backend.api.shared import config, server_config

router = APIRouter(prefix="/api/v1/options", dependencies=get_dependencies())


@router.get("/models")
async def get_models() -> list[str]:
    """Get all language models supported by the system.

    Retrieves a comprehensive list of available LLM models from supported
    providers (OpenAI, Anthropic, Gemini, Grok). Results are deduplicated
    and sorted alphabetically.

    Returns:
        list[str]: A sorted list of unique model identifiers (e.g.,
            ["gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro"]).

    Examples:
        >>> curl http://localhost:3000/api/options/models
        ["claude-3-5-sonnet", "gemini-1.5-pro", "gpt-4o", ...]

    Notes:
        - Results are cached and deduplicated
        - Focuses on famous, well-supported models

    """
    return get_supported_llm_models(config)


@router.get("/agents")
async def get_agents() -> list[str]:
    """Get all available AI agents supported by the system.

    Retrieves a list of all registered agent implementations. Agents are
    automatically discovered and registered via the engines module import.

    Returns:
        list[str]: A sorted list of agent names available for selection
            (e.g., ["gpt-4-agent", "codebase-agent", "research-agent"]).

    Examples:
        >>> curl http://localhost:3000/api/options/agents
        ["agent-1", "agent-2", "code-analyzer-agent", ...]

    Notes:
        - Agents are auto-registered from backend.engines module
        - List includes both default and custom agents

    """
    return sorted(Agent.list_agents())


@router.get("/security-analyzers")
async def get_security_analyzers() -> list[str]:
    """Get all supported security analyzers.

    Retrieves a list of all security analysis tools available for analyzing
    code security issues, vulnerabilities, and compliance concerns.

    Returns:
        list[str]: A sorted list of security analyzer names (e.g.,
            ["semgrep", "bandit", "sonarqube"]).

    Examples:
        >>> curl http://localhost:3000/api/options/security-analyzers
        ["bandit", "semgrep", "sonarqube", ...]

    Notes:
        - Security analyzers must be initialized per-conversation
        - Availability depends on system configuration

    """
    return sorted(SecurityAnalyzers.keys())


@router.get("/config")
async def get_config() -> dict[str, Any]:
    """Get current server configuration and settings.

    Retrieves the complete active server configuration including deployment
    mode, feature flags, API settings, and other runtime parameters.

    Returns:
        dict[str, Any]: Dictionary containing all active configuration parameters
            with structure depending on server_config implementation:
            - app_mode: Application mode ("SAAS", "STANDALONE", etc.)
            - api_base_url: Base URL for API endpoints
            - workspace_base: Base path for workspace directory
            - feature_flags: Enabled features
            - Other server-specific settings

    Examples:
        >>> curl http://localhost:3000/api/options/config
        {
            "app_mode": "SAAS",
            "api_base_url": "https://api.example.com",
            "workspace_base": "/data/workspace",
            ...
        }

    Notes:
        - This is a public endpoint; sensitive credentials are not included
        - Configuration is cached in server_config singleton

    """
    return server_config.get_config()
