"""LLM integration and communication layer.

Classes:
    RegistryEvent
    LLMRegistry

Functions:
    request_extraneous_completion
    get_llm_from_agent_config
    get_llm
    get_active_llm
    subscribe
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from backend.core.logger import FORGE_logger as logger
from backend.llm.llm import LLM

if TYPE_CHECKING:
    from backend.core.config.agent_config import AgentConfig
    from backend.core.config.forge_config import ForgeConfig
    from backend.core.config.llm_config import LLMConfig


@dataclass
class RegistryEvent:
    """Metadata emitted when LLM registry mutates (add/remove providers)."""

    event_type: str = "update"
    key: str | None = None
    llm: LLM | None = None
    service_id: str | None = None


class LLMRegistry:
    """Central registry for managing LLM instances across the application.

    Provides singleton-style management of LLM connections, ensuring each
    service uses a consistent LLM configuration and supporting hot-swapping
    of models via subscription notifications.
    """

    def __init__(
        self,
        config: ForgeConfig,
        agent_cls: str | None = None,
        retry_listener: Callable[[int, int], None] | None = None,
    ) -> None:
        """Initialize LLM registry with configuration.

        Args:
            config: Forge configuration with LLM settings
            agent_cls: Optional agent class name to determine default LLM
            retry_listener: Optional callback for retry events (attempt, max_attempts)

        """
        self.registry_id = str(uuid4())
        self.config = copy.deepcopy(config)
        self.retry_listner = retry_listener
        self.agent_to_llm_config = self.config.get_agent_to_llm_config_map()
        self.service_to_llm: dict[str, LLM] = {}
        self.subscriber: Callable[[Any], None] | None = None
        selected_agent_cls = agent_cls or self.config.default_agent
        agent_name = selected_agent_cls if selected_agent_cls is not None else "agent"
        llm_config = self.config.get_llm_config_from_agent(agent_name)
        self.active_agent_llm: LLM = self.get_llm("agent", llm_config)

    def _create_new_llm(
        self, service_id: str, config: LLMConfig, with_listener: bool = True
    ) -> LLM:
        """Create and register a new LLM instance.

        Args:
            service_id: Unique identifier for this LLM service
            config: LLM configuration settings
            with_listener: Whether to attach retry listener

        Returns:
            Newly created LLM instance

        """
        if with_listener:
            llm = LLM(
                service_id=service_id, config=config, retry_listener=self.retry_listner
            )
        else:
            llm = LLM(service_id=service_id, config=config)
        self.service_to_llm[service_id] = llm
        self.notify(RegistryEvent(llm=llm, service_id=service_id))
        return llm

    def request_extraneous_completion(
        self,
        service_id: str,
        llm_config: LLMConfig,
        messages: list[dict[str, str]],
    ) -> str:
        """Request LLM completion for one-off tasks outside agent loop.

        Used for auxiliary tasks like analysis or validation. Creates
        service without retry listener to avoid interfering with metrics.

        Args:
            service_id: Service identifier for this request
            llm_config: LLM configuration
            messages: Conversation messages for completion

        Returns:
            Generated completion text

        """
        logger.info("extraneous completion: %s", service_id)
        if service_id not in self.service_to_llm:
            self._create_new_llm(
                config=llm_config, service_id=service_id, with_listener=False
            )
        llm = self.service_to_llm[service_id]
        response = llm.completion(messages=messages)
        return response.choices[0].message.content.strip()

    def get_llm_from_agent_config(self, service_id: str, agent_config: AgentConfig):
        """Get or create LLM from agent configuration.

        Args:
            service_id: Service identifier
            agent_config: Agent configuration containing LLM settings

        Returns:
            LLM instance for the service

        """
        llm_config = self.config.get_llm_config_from_agent_config(agent_config)
        if service_id in self.service_to_llm:
            return self.service_to_llm[service_id]
        return self._create_new_llm(config=llm_config, service_id=service_id)

    def get_llm(self, service_id: str, config: LLMConfig | None = None):
        """Get existing LLM or create new one with given config.

        Args:
            service_id: Unique service identifier
            config: LLM configuration (required for new services)

        Returns:
            LLM instance for the service

        Raises:
            ValueError: If requesting existing service with different config,
                       or new service without config

        """
        logger.info(
            "[LLM registry %s]: Registering service for %s",
            self.registry_id,
            service_id,
        )
        if (
            service_id in self.service_to_llm
            and self.service_to_llm[service_id].config != config
        ):
            msg = f"Requesting same service ID {service_id} with different config, use a new service ID"
            raise ValueError(msg)
        if service_id in self.service_to_llm:
            return self.service_to_llm[service_id]
        if not config:
            msg = "Requesting new LLM without specifying LLM config"
            raise ValueError(msg)
        return self._create_new_llm(config=config, service_id=service_id)

    def get_active_llm(self) -> LLM:
        """Get the currently active agent LLM.

        Returns:
            Active LLM instance used by the main agent

        """
        return self.active_agent_llm

    def _set_active_llm(self, service_id) -> None:
        """Set the active agent LLM by service ID.

        Args:
            service_id: Service ID to set as active

        Raises:
            ValueError: If service ID not registered

        """
        if service_id not in self.service_to_llm:
            msg = f"Unrecognized service ID: {service_id}"
            raise ValueError(msg)
        self.active_agent_llm = self.service_to_llm[service_id]

    def subscribe(self, callback: Callable[[RegistryEvent], None]) -> None:
        """Subscribe to LLM registry events (creation, activation).

        Immediately notifies subscriber of current active LLM.

        Args:
            callback: Function to call with RegistryEvent on changes

        """
        self.subscriber = callback
        self.notify(
            RegistryEvent(
                llm=self.active_agent_llm, service_id=self.active_agent_llm.service_id
            )
        )

    def notify(self, event: RegistryEvent) -> None:
        """Notify subscriber of registry event.

        Args:
            event: Event containing LLM and service_id information

        """
        if self.subscriber:
            try:
                self.subscriber(event)
            except Exception as e:
                logger.warning("Failed to emit event: %s", e)
