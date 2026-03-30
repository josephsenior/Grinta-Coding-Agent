"""Pydantic model rebuild orchestration.

Extracted from ``config/utils.py`` to keep the main config orchestrator lean.
Handles the one-time forward-reference resolution for all config models.
"""

from __future__ import annotations

from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.config.agent_config import AgentConfig
from backend.core.config.extended_config import ExtendedConfig
from backend.core.config.app_config import AppConfig
from backend.core.config.llm_config import LLMConfig
from backend.core.config.mcp_config import MCPConfig
from backend.core.config.runtime_config import RuntimeConfig
from backend.core.config.security_config import SecurityConfig

_MODELS_REBUILT = False


def rebuild_config_models() -> None:
    """Rebuild all Pydantic config models to resolve forward references.

    Must be called once before the first ``AppConfig()`` instantiation.
    Subsequent calls are no-ops (the rebuilds are idempotent but not free).
    """
    global _MODELS_REBUILT
    if _MODELS_REBUILT:
        return

    from backend.core.config.compactor_config import (
        AmortizedPruningCompactorConfig,
        BrowserOutputCompactorConfig,
        CompactorPipelineConfig,
        ConversationWindowCompactorConfig,
        LLMAttentionCompactorConfig,
        LLMSummarizingCompactorConfig,
        NoOpCompactorConfig,
        ObservationMaskingCompactorConfig,
        RecentEventsCompactorConfig,
        SmartCompactorConfig,
        StructuredSummaryCompactorConfig,
    )
    from backend.core.config.permissions_config import PermissionsConfig
    from backend.security.safety_config import SafetyConfig

    # 1. Base configs (no dependencies)
    for cls in (
        LLMConfig,
        RuntimeConfig,
        SecurityConfig,
        ExtendedConfig,
        MCPConfig,
        PermissionsConfig,
        SafetyConfig,
    ):
        cls.model_rebuild()

    # 2. Compactor configs (depend on LLMConfig)
    compactor_ns = {
        "LLMConfig": LLMConfig,
        "Field": Field,
        "BaseModel": BaseModel,
        "ConfigDict": ConfigDict,
        "ValidationError": ValidationError,
        "Literal": Literal,
        "cast": cast,
    }
    for compactor_cls in (
        NoOpCompactorConfig,
        ObservationMaskingCompactorConfig,
        BrowserOutputCompactorConfig,
        RecentEventsCompactorConfig,
        LLMSummarizingCompactorConfig,
        AmortizedPruningCompactorConfig,
        LLMAttentionCompactorConfig,
        StructuredSummaryCompactorConfig,
        CompactorPipelineConfig,
        ConversationWindowCompactorConfig,
        SmartCompactorConfig,
    ):
        compactor_cls.model_rebuild(_types_namespace=compactor_ns)

    # 3. Composite configs
    AgentConfig.model_rebuild()
    AppConfig.model_rebuild()

    _MODELS_REBUILT = True
