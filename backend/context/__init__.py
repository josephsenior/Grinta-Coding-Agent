"""Persistence and retrieval primitives for Forge conversational memory."""

# Lazy imports to avoid heavy dependencies at package-level import.


def __getattr__(name: str):
    if name == "Memory":
        from backend.context.agent_memory import Memory

        return Memory
    if name == "ConversationMemory":
        from backend.context.conversation_memory import ConversationMemory

        return ConversationMemory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
