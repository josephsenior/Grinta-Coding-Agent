"""Tests for backend.gateway.store_factory delegation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.gateway.store_factory import (
    get_conversation_store_instance,
    get_secrets_store_instance,
    get_settings_store_instance,
)


@pytest.mark.asyncio
async def test_get_conversation_store_instance_awaits_get_instance() -> None:
    impl = MagicMock()
    impl.get_instance = AsyncMock(return_value="conv")
    config = MagicMock()
    out = await get_conversation_store_instance(impl, config, "uid")
    assert out == "conv"
    impl.get_instance.assert_awaited_once_with(config, "uid")


@pytest.mark.asyncio
async def test_get_settings_store_instance_awaits_get_instance() -> None:
    impl = MagicMock()
    impl.get_instance = AsyncMock(return_value="settings")
    config = MagicMock()
    out = await get_settings_store_instance(impl, config, None)
    assert out == "settings"
    impl.get_instance.assert_awaited_once_with(config, None)


@pytest.mark.asyncio
async def test_get_secrets_store_instance_awaits_get_instance() -> None:
    impl = MagicMock()
    impl.get_instance = AsyncMock(return_value="secrets")
    config = MagicMock()
    out = await get_secrets_store_instance(impl, config, "u")
    assert out == "secrets"
    impl.get_instance.assert_awaited_once_with(config, "u")
