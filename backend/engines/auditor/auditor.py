"""Enhanced read-only code auditor with structure-aware exploration.

Capabilities:
1. Ultimate Editor (read-only mode) — Tree-sitter symbol exploration
2. Semantic Search — find code by meaning, not just keywords
3. File Caching — avoids redundant reads for frequently accessed files
"""

import os
from typing import TYPE_CHECKING, Any

from backend.llm.llm_registry import LLMRegistry

if TYPE_CHECKING:
    ChatCompletionToolParam = Any
    ModelResponse = Any
    from backend.events.action import Action

from backend.core.config import AgentConfig
from backend.core.logger import forge_logger as logger
from backend.engines.auditor import function_calling as readonly_function_calling
from backend.engines.auditor.tools.file_cache import FileCache
from backend.engines.orchestrator.orchestrator import Orchestrator
from backend.utils.prompt import (
    UNINITIALIZED_PROMPT_MANAGER as _UNINITIALIZED,
)
from backend.utils.prompt import (
    PromptManager,
    _UninitializedPromptManager,
)


class Auditor(Orchestrator):
    """Enhanced read-only auditor with structure-aware exploration and caching.

    Extends the base ``Orchestrator`` in read-only mode with:
    - Tree-sitter symbol exploration (40+ languages)
    - Semantic code search
    - File-level caching to reduce repeated reads
    """

    VERSION = "2.0"
    # Override base class attribute - initialized lazily via property
    # Use sentinel object instead of None for better type safety
    _prompt_manager: PromptManager | _UninitializedPromptManager  # type: ignore[assignment]
    """
    Enhanced read-only code exploration engine.

    Features:
    - Structure-aware exploration (Tree-sitter for 40+ languages)
    - Semantic search (find code by meaning)
    - File caching (reduces redundant reads)
    - All read-only tools from Orchestrator
    """

    def __init__(self, config: AgentConfig, llm_registry: LLMRegistry) -> None:
        """Initialize Ultimate Auditor.

        Args:
            config: Agent configuration
            llm_registry: LLM registry

        """
        super().__init__(config, llm_registry)
        # Override base class initialization - use lazy initialization via property
        # The base class creates _prompt_manager immediately in __init__, but we want
        # lazy initialization. We use a sentinel object for runtime type safety.
        # Type ignore is needed here because we're intentionally narrowing the base class
        # type (PromptManager) to allow lazy initialization. The property getter ensures
        # type safety at runtime by always returning a PromptManager.
        self._prompt_manager = _UNINITIALIZED  # type: ignore[assignment]

        # Initialize file cache (NEW!)
        self.file_cache = FileCache(
            max_cache_size=getattr(config, "readonly_cache_size", 100),
            ttl_seconds=getattr(config, "readonly_cache_ttl", 300),
            enable_mtime_check=True,
        )

        logger.info("✅ Ultimate Auditor initialized")
        logger.info("   - Ultimate Editor: Structure-aware exploration (40+ languages)")
        logger.info("   - Semantic Search: Find code by meaning")
        logger.info("   - File Caching: Instant repeated access")
        logger.debug(
            "TOOLS loaded for Ultimate Auditor: %s",
            ", ".join([tool.get("function").get("name") for tool in self.tools]),
        )

    @property
    def prompt_manager(self) -> PromptManager:
        """Lazily initialize and return the enhanced prompt manager for ultimate read-only agent."""
        if isinstance(self._prompt_manager, _UninitializedPromptManager):
            self._prompt_manager = PromptManager(
                prompt_dir=os.path.join(os.path.dirname(__file__), "prompts"),
                system_prompt_filename="system_prompt.j2",
            )
        return self._prompt_manager

    def _get_tools(self) -> list["ChatCompletionToolParam"]:
        """Get tools including Ultimate Editor and Semantic Search."""
        # Get base read-only tools
        tools = readonly_function_calling.get_tools()

        # Add Ultimate Editor (read-only mode)
        try:
            from backend.engines.auditor.tools.ultimate_explorer import (
                create_ultimate_explorer_tool,
            )

            tools.append(create_ultimate_explorer_tool())
            logger.debug("Added Ultimate Explorer tool")
        except Exception as e:
            logger.warning("Could not load Ultimate Explorer: %s", e)

        # Add Semantic Search
        try:
            from backend.engines.auditor.tools.semantic_search import (
                create_semantic_search_tool,
            )

            tools.append(create_semantic_search_tool())
            logger.debug("Added Semantic Search tool")
        except Exception as e:
            logger.warning("Could not load Semantic Search: %s", e)

        return tools

    def set_mcp_tools(self, mcp_tools: list[dict]) -> None:
        """Sets the list of MCP tools for the agent.

        Args:
            mcp_tools (list[dict]): The list of MCP tools.

        """
        logger.warning(
            "Auditor does not support MCP tools. MCP tools will be ignored by the agent."
        )

    def response_to_actions(self, response: "ModelResponse") -> list["Action"]:
        """Convert response to actions, with caching support."""
        actions = readonly_function_calling.response_to_actions(
            response, mcp_tool_names=list(self.mcp_tools.keys())
        )

        # Track cache stats periodically
        stats = self.file_cache.get_stats()
        if stats["total_requests"] > 0 and stats["total_requests"] % 50 == 0:
            logger.info(
                "📊 Cache stats: %s%% hit rate (%s/%s requests)",
                stats["hit_rate_percent"],
                stats["hits"],
                stats["total_requests"],
            )

        return actions

    def get_cache_stats(self) -> dict:
        """Get file cache statistics."""
        return self.file_cache.get_stats()

    def clear_cache(self) -> None:
        """Clear file cache."""
        self.file_cache.clear()
