"""Tests for backend.gateway.graceful_shutdown."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

import backend.gateway.graceful_shutdown as gs


@pytest.fixture(autouse=True)
def _reset_graceful_shutdown_state() -> None:
    gs._shutdown_handlers.clear()
    gs._shutdown_in_progress = False
    yield
    gs._shutdown_handlers.clear()
    gs._shutdown_in_progress = False


def test_is_shutting_down_false_initially() -> None:
    assert gs.is_shutting_down() is False


def _patch_request_shutdown() -> patch:
    return patch("backend.utils.shutdown_listener.request_process_shutdown")


def test_graceful_shutdown_runs_sync_handler() -> None:
    called: list[int] = []

    def sync_handler() -> None:
        called.append(1)

    gs.register_shutdown_handler(sync_handler)

    async def _run() -> None:
        with _patch_request_shutdown():
            await gs.graceful_shutdown()

    asyncio.run(_run())

    assert called == [1]
    assert gs.is_shutting_down() is True


def test_graceful_shutdown_runs_async_handler() -> None:
    called: list[int] = []

    async def async_handler() -> None:
        called.append(2)

    gs.register_shutdown_handler(async_handler)

    async def _run() -> None:
        with _patch_request_shutdown():
            await gs.graceful_shutdown()

    asyncio.run(_run())

    assert called == [2]


def test_graceful_shutdown_idempotent_second_call() -> None:
    n = {"c": 0}

    def h() -> None:
        n["c"] += 1

    gs.register_shutdown_handler(h)

    async def _run() -> None:
        with _patch_request_shutdown():
            await gs.graceful_shutdown()
            await gs.graceful_shutdown()

    asyncio.run(_run())

    assert n["c"] == 1


def test_graceful_shutdown_handler_error_does_not_abort_others() -> None:
    trace: list[str] = []

    def bad() -> None:
        trace.append("bad")
        raise RuntimeError("handler failed")

    def good() -> None:
        trace.append("good")

    gs.register_shutdown_handler(bad)
    gs.register_shutdown_handler(good)

    async def _run() -> None:
        with _patch_request_shutdown():
            await gs.graceful_shutdown()

    asyncio.run(_run())

    assert trace == ["bad", "good"]
