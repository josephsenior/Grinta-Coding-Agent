"""Concrete condenser implementations used by the memory subsystem."""

from backend.context.condenser.strategies.amortized_forgetting_condenser import (
    AmortizedForgettingCondenser,
)
from backend.context.condenser.strategies.auto_condenser import AutoCondenser
from backend.context.condenser.strategies.conversation_window_condenser import (
    ConversationWindowCondenser,
)
from backend.context.condenser.strategies.llm_attention_condenser import (
    ImportantEventSelection,
    LLMAttentionCondenser,
)
from backend.context.condenser.strategies.llm_summarizing_condenser import (
    LLMSummarizingCondenser,
)
from backend.context.condenser.strategies.no_op_condenser import NoOpCondenser
from backend.context.condenser.strategies.observation_masking_condenser import (
    ObservationMaskingCondenser,
)
from backend.context.condenser.strategies.pipeline import CondenserPipeline
from backend.context.condenser.strategies.recent_events_condenser import (
    RecentEventsCondenser,
)
from backend.context.condenser.strategies.semantic_condenser import (
    SemanticCondenser,
)
from backend.context.condenser.strategies.structured_summary_condenser import (
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
