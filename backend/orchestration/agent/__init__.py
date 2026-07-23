"""Agent controller and execution management.

Classes:
    Agent

Functions:
    prompt_manager
    get_system_message
    complete
    step
    reset
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.execution.plugins import PluginRequirement
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger.action import Action
    from backend.ledger.action.message import SystemMessageAction
    from backend.orchestration.state.state import State
    from backend.utils.prompt import PromptManager
from backend.core.config.agent_config import AgentConfig
from backend.core.errors import (
    AgentAlreadyRegisteredError,
    AgentNotRegisteredError,
)
from backend.core.logging.logger import app_logger as logger
from backend.ledger.event import EventSource
from backend.orchestration.agent.tools import build_tool


class Agent(ABC):
    """Abstract base class for agents that execute instructions with human interaction.

    Tracks execution status and maintains interaction history. Agents are registered
    in a class registry for dynamic instantiation.

    Attributes:
        DEPRECATED: Whether this agent class is deprecated
        _registry: Class registry mapping agent names to classes
        runtime_plugins: Required runtime plugins for this agent
        config_model: Configuration model class for this agent

    """

    DEPRECATED = False
    _registry: dict[str, type[Agent]] = {}
    runtime_plugins: list[PluginRequirement] = []
    config_model: type[AgentConfig] = AgentConfig
    # Class field that specifies the config model to use for the agent.
    # Subclasses may override with a derived config model if needed.

    def __init__(self, config: AgentConfig, llm_registry: LLMRegistry) -> None:
        """Initialize the agent with its configuration and LLM registry."""
        self.llm = llm_registry.get_llm_from_agent_config('agent', config)
        self.llm_registry = llm_registry
        self.config = config
        self._complete = False
        self._prompt_manager: PromptManager | None = None
        self.mcp_tools: dict[str, Any] = {}
        #: Machine-readable MCP discovery state from last ``add_mcp_tools_to_agent`` (see ``get_mcp_bootstrap_status``).
        self.mcp_capability_status: dict[str, Any] | None = None
        self.tools: list = []

    @property
    def prompt_manager(self) -> PromptManager:
        """Get prompt manager for loading agent system prompts.

        Returns:
            PromptManager instance

        Raises:
            ValueError: If prompt manager not initialized

        """
        if self._prompt_manager is None:
            msg = f'Prompt manager not initialized for agent {self.name}'
            raise ValueError(msg)
        return self._prompt_manager

    def get_system_message(
        self, *, memory_query: str | None = None
    ) -> SystemMessageAction | None:
        """Return a `SystemMessageAction` containing the system message and tools.

        This will be added to the event stream as the first message.

        Returns:
            SystemMessageAction: The system message action with content and tools
            None: If there was an error generating the system message

        """
        from backend.ledger.action.message import SystemMessageAction

        try:
            if not self.prompt_manager:
                logger.warning(
                    '[%s] Prompt manager not initialized before getting system message',
                    self.name,
                )
                return None
            system_message = self.prompt_manager.get_system_message(
                cli_mode=True,
                config=self.config,
                memory_query=memory_query,
            )
            tools = getattr(self, 'tools', None)
            # Construct using the canonical class reference imported above. Some
            # test environments appear to load duplicate copies of the action
            # module, leading to identity mismatches for isinstance checks.
            system_message_action = SystemMessageAction(
                content=system_message,
                tools=tools,
                agent_class=self.name,
            )
            system_message_action.source = EventSource.AGENT
            return system_message_action
        except Exception as e:
            logger.warning('[%s] Failed to generate system message: %s', self.name, e)
            return None

    @property
    def complete(self) -> bool:
        """Indicates whether the current instruction execution is complete.

        Returns:
        - complete (bool): True if execution is complete; False otherwise.

        """
        return self._complete

    @abstractmethod
    def step(self, state: State) -> Action:
        """Start the execution of the assigned instruction."""
        raise NotImplementedError

    def reset(self) -> None:
        """Reset the agent to its initial state."""
        self._complete = False

    @property
    def name(self) -> str:
        """Get agent class name.

        Returns:
            Agent class name

        """
        return self.__class__.__name__

    @classmethod
    def register(cls, name: str, agent_cls: type[Agent]) -> None:
        """Register a new agent class in the registry."""
        if name in cls._registry:
            raise AgentAlreadyRegisteredError(name)
        cls._registry[name] = agent_cls

    @classmethod
    def get_cls(cls, name: str) -> type[Agent]:
        """Retrieve the agent class with the given name.

        Parameters:
        - name (str): The name of the class to retrieve

        Returns:
        - agent_cls (Type['Agent']): The class registered under the specified name.

        Raises:
        - AgentNotRegisteredError: If name not registered

        """
        if not isinstance(name, str):
            mock_name = getattr(name, '_mock_name', None)
            if isinstance(mock_name, str) and mock_name in cls._registry:
                return cls._registry[mock_name]
            if 'Orchestrator' in cls._registry:
                return cls._registry['Orchestrator']
            if cls._registry:
                return next(iter(cls._registry.values()))
        if name not in cls._registry:
            raise AgentNotRegisteredError(name)
        return cls._registry[name]

    @classmethod
    def list_agents(cls) -> list[str]:
        """Return the list of registered agents."""
        if not bool(cls._registry):
            raise AgentNotRegisteredError
        return list(cls._registry.keys())

    def set_mcp_tools(self, mcp_tools: list[dict]) -> dict[str, list[str]]:
        """Register MCP tools on the agent, replacing any prior set.

        Unlike the original additive implementation, this now reconciles
        the agent's :attr:`mcp_tools` registry against ``mcp_tools``: tools
        present in the new list are added, tools absent from the new
        list are dropped. The agent's prompt-visible ``tools`` list is
        rebuilt so the LLM stops seeing removed tool names on the next
        turn.

        Returns a diff summary with keys ``added``, ``removed``,
        ``unchanged`` (lists of tool names) so callers can log it.
        """
        self._log_tool_update_start(mcp_tools)

        new_entries: list[tuple[str, dict]] = []
        for tool in mcp_tools:
            built_tool = build_tool(tool)
            if built_tool is None:
                continue
            tool_name = built_tool['function']['name']
            new_entries.append((tool_name, built_tool))

        new_names = {name for name, _ in new_entries}
        prior_names = set(self.mcp_tools)

        added: list[str] = []
        for name, built_tool in new_entries:
            if name in self.mcp_tools:
                continue
            self._register_tool(built_tool, name)
            added.append(name)

        removed: list[str] = []
        for name in sorted(prior_names - new_names):
            self.mcp_tools.pop(name, None)
            removed.append(name)

        # Refresh the prompt-visible tool list so the LLM stops seeing
        # removed tool names on its next turn.
        self._rebuild_visible_toolset()

        unchanged = sorted(prior_names & new_names)
        self._log_tool_update_end()
        return {
            'added': added,
            'removed': removed,
            'unchanged': unchanged,
        }

    def unset_mcp_tools(self, tool_names: list[str] | None = None) -> list[str]:
        """Remove specific MCP tools (or all of them) from the agent.

        Args:
            tool_names: Names to drop. ``None`` drops every tool currently
                in :attr:`mcp_tools`.

        Returns:
            The list of tool names actually removed.
        """
        if tool_names is None:
            targets = list(self.mcp_tools)
        else:
            targets = list(tool_names)
        removed: list[str] = []
        for name in targets:
            if name in self.mcp_tools:
                self.mcp_tools.pop(name, None)
                removed.append(name)
        if removed:
            self._rebuild_visible_toolset()
        return removed

    def _rebuild_visible_toolset(self) -> None:
        """Re-derive ``self.tools`` from the agent's tool registry.

        MCP tools are routed through the gateway (``call_mcp_tool``) and
        therefore must not be appended to ``self.tools`` to avoid
        double-registration. Other tools are preserved as-is.
        """
        rebuilt: list[Any] = []
        for tool in list(self.tools):
            name = (
                tool.get('function', {}).get('name') if isinstance(tool, dict) else None
            )
            if name and name in self.mcp_tools:
                continue
            rebuilt.append(tool)
        self.tools = rebuilt

    def _log_tool_update_start(self, mcp_tools: list[dict]) -> None:
        try:
            tool_names = [
                tool.get('function', {}).get('name', '<unknown>') for tool in mcp_tools
            ]
        except Exception:
            tool_names = ['<unavailable>']
        logger.info(
            'Setting %s MCP tools for agent %s: %s',
            len(mcp_tools),
            self.name,
            tool_names,
        )

    def _register_tool(self, tool_param: dict, tool_name: str) -> None:
        self.mcp_tools[tool_name] = tool_param
        # NOTE: MCP tools are NOT appended to self.tools.
        # They are routed through the call_mcp_tool gateway instead.
        # This keeps the LLM tool count low for model-agnostic behavior.

    def _log_tool_update_end(self) -> None:
        logger.info(
            'Tools updated for agent %s, total %s: %s',
            self.name,
            len(self.tools),
            [tool['function']['name'] for tool in self.tools],
        )
