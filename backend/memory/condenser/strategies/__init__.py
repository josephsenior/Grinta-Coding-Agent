"""Concrete condenser implementations used by the memory subsystem."""

from backend.memory.condenser.strategies.amortized_forgetting_condenser import (
    AmortizedForgettingCondenser,
)
from backend.memory.condenser.strategies.auto_condenser import AutoCondenser
from backend.memory.condenser.strategies.conversation_window_condenser import (
    ConversationWindowCondenser,
)
from backend.memory.condenser.strategies.llm_attention_condenser import (
    ImportantEventSelection,
    LLMAttentionCondenser,
)
from backend.memory.condenser.strategies.llm_summarizing_condenser import (
    LLMSummarizingCondenser,
)
from backend.memory.condenser.strategies.no_op_condenser import NoOpCondenser
from backend.memory.condenser.strategies.observation_masking_condenser import (
    ObservationMaskingCondenser,
)
from backend.memory.condenser.strategies.pipeline import CondenserPipeline
from backend.memory.condenser.strategies.recent_events_condenser import (
    RecentEventsCondenser,
)
from backend.memory.condenser.strategies.semantic_condenser import (
    SemanticCondenser,
)
from backend.memory.condenser.strategies.structured_summary_condenser import (
    StructuredSummaryCondenser,
)

__all__ = [
    "AmortizedForgettingCondenser",
    "AutoCondenser",
    "CondenserPipeline",
    "ConversationWindowCondenser",
    "ImportantEventSelection",
    "LLMAttentionCondenser",
    "LLMSummarizingCondenser",
    "NoOpCondenser",
    "ObservationMaskingCondenser",
    "RecentEventsCondenser",
    "SemanticCondenser",
    "StructuredSummaryCondenser",
]
