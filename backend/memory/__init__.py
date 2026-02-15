"""Persistence and retrieval primitives for Forge conversational memory."""

# Lazy imports to avoid heavy dependencies at package-level import.


def __getattr__(name: str):  # noqa: N807
    if name == "Memory":
        from backend.memory.agent_memory import Memory

        return Memory
    if name == "ConversationMemory":
        from backend.memory.conversation_memory import ConversationMemory

        return ConversationMemory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
