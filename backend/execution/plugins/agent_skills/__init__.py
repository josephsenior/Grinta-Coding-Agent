"""Agent skills plugin metadata and placeholder runtime integration."""

from dataclasses import dataclass

from backend.ledger.action import Action
from backend.ledger.observation import Observation
from backend.execution.plugins.agent_skills import agentskills
from backend.execution.plugins.requirement import Plugin, PluginRequirement


@dataclass
class AgentSkillsRequirement(PluginRequirement):
    """Plugin requirement — documentation-only (no runtime dispatch).

    The agent-skills package is installed directly inside the runtime and
    invoked via Python imports in bash commands.  This requirement object
    exists solely to inject the ``DOCUMENTATION`` string into the agent's
    system prompt; there is no ``Plugin.run()`` pathway.
    """

    name: str = "agent_skills"
    metadata_only: bool = True
    documentation: str = agentskills.DOCUMENTATION


class AgentSkillsPlugin(Plugin):
    """Documentation-only plugin — contributes skill docs to prompts.

    Skills are executed inside the runtime via direct Python imports,
    **not** through this plugin's ``run()`` method.  Calling ``run()``
    is a programming error and raises ``NotImplementedError`` with a
    clear message.
    """

    name: str = "agent_skills"

    async def initialize(self, username: str) -> None:
        """No-op — skills are installed at runtime build time."""

    async def run(self, action: Action) -> Observation:
        """Not implemented — skills run inside the runtime, not via plugin dispatch."""
        raise NotImplementedError(
            "AgentSkillsPlugin is metadata-only (metadata_only=True on its "
            "PluginRequirement). Skills are executed inside the runtime via "
            "direct Python imports, not through Plugin.run(). If you reached "
            "this code path, the runtime dispatch logic has a bug."
        )
