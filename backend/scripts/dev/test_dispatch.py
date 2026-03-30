import asyncio
import logging

from backend.core.config import AppConfig
from backend.inference.llm_registry import LLMRegistry
from backend.gateway.services.conversation_stats import ConversationStats
from backend.gateway.session.session import Session
from backend.persistence.local_file_store import LocalFileStore


class DummySIO:
    manager: dict[str, str] = {}

    async def emit(self, *args: object, **kwargs: object) -> None:
        logging.getLogger(__name__).info("SIO EMIT: %s %s", args, kwargs)


async def run_test():
    config = AppConfig()
    llm_registry = LLMRegistry(config)
    fs = LocalFileStore("logs")
    stats = ConversationStats(fs, "test-sid", "user1")
    sio = DummySIO()
    session = Session("test-sid", config, llm_registry, stats, fs, sio, user_id="user1")
    data = {"action": "message", "args": {"content": "sop: test orchestration"}}
    await session.dispatch(data)
    await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(run_test())

