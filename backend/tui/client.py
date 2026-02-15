"""Async client for the Forge backend — REST (httpx) + WebSocket (Socket.IO).

This module is the *only* place the TUI touches the network.  Every other
TUI component talks through :class:`ForgeClient`.

Usage::

    client = ForgeClient("http://localhost:3000")
    await client.connect()
    convos = await client.list_conversations()
    c = await client.create_conversation("Fix the login bug")
    await client.join_conversation(c["conversation_id"], on_event=my_handler)
    await client.send_message("Please also add tests")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

import httpx
import socketio  # type: ignore[import-untyped]

logger = logging.getLogger("forge.tui.client")

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationInfo:
    """Lightweight representation of a conversation returned by the API."""

    conversation_id: str
    title: str
    status: str = "unknown"
    created_at: str = ""
    last_updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationInfo:
        return cls(
            conversation_id=data.get("conversation_id", ""),
            title=data.get("title", data.get("conversation_id", "Untitled")),
            status=data.get("status", data.get("conversation_status", "unknown")),
            created_at=data.get("created_at", ""),
            last_updated_at=data.get("last_updated_at", data.get("updated_at", "")),
        )


@dataclass
class ServerConfig:
    """Subset of ``/api/config`` that the TUI cares about."""

    app_mode: str = "oss"
    file_uploads_allowed: bool = True
    max_file_size_mb: int = 0
    security_model: str = "none"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerConfig:
        return cls(
            app_mode=data.get("APP_MODE", "oss"),
            file_uploads_allowed=data.get("FILE_UPLOADS_ALLOWED", True),
            max_file_size_mb=data.get("MAX_FILE_SIZE_MB", 0),
            security_model=data.get("SECURITY_MODEL", "none"),
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass
class ForgeClient:
    """Async HTTP + Socket.IO client facade for the Forge API."""

    base_url: str = "http://localhost:3000"

    # ── internal state ────────────────────────────────────────────
    _http: httpx.AsyncClient = field(init=False, repr=False)
    _sio: socketio.AsyncClient = field(init=False, repr=False)
    _event_callback: EventCallback | None = field(default=None, init=False, repr=False)
    _connected_conversation_id: str | None = field(default=None, init=False, repr=False)
    _connect_event: asyncio.Event = field(
        default_factory=asyncio.Event, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=f"{self.base_url}/api",
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
        self._sio = socketio.AsyncClient(
            logger=False,
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=1,
        )
        self._register_sio_handlers()

    # ── lifecycle ─────────────────────────────────────────────────

    async def close(self) -> None:
        """Tear down HTTP + WS connections."""
        if self._sio.connected:
            await self._sio.disconnect()
        await self._http.aclose()

    # ── REST helpers ──────────────────────────────────────────────

    async def _get(self, path: str, **kwargs: Any) -> Any:
        resp = await self._http.get(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, **kwargs: Any) -> Any:
        resp = await self._http.post(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str) -> bool:
        resp = await self._http.delete(path)
        return resp.is_success

    async def _patch(self, path: str, **kwargs: Any) -> Any:
        resp = await self._http.patch(path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # ── conversations ─────────────────────────────────────────────

    async def list_conversations(
        self,
        page: int = 1,
        limit: int = 20,
    ) -> list[ConversationInfo]:
        """GET /api/conversations → list of conversations."""
        data = await self._get(
            "/conversations",
            params={"page_id": page, "limit": limit},
        )
        results = data.get("results", data) if isinstance(data, dict) else data
        if not isinstance(results, list):
            results = []
        return [ConversationInfo.from_dict(c) for c in results]

    async def create_conversation(
        self,
        initial_message: str | None = None,
        conversation_instructions: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/conversations → create & start a new session.

        Returns the raw response dict (contains ``conversation_id``).
        """
        payload: dict[str, Any] = {}
        if initial_message:
            payload["initial_user_msg"] = initial_message
        if conversation_instructions:
            payload["conversation_instructions"] = conversation_instructions
        return await self._post("/conversations", json=payload)

    async def delete_conversation(self, conversation_id: str) -> bool:
        """DELETE /api/conversations/{id}."""
        return await self._delete(f"/conversations/{conversation_id}")

    async def start_agent(self, conversation_id: str) -> dict[str, Any]:
        """POST /api/conversations/{id}/start."""
        return await self._post(f"/conversations/{conversation_id}/start")

    async def stop_agent(self, conversation_id: str) -> dict[str, Any]:
        """POST /api/conversations/{id}/stop."""
        return await self._post(f"/conversations/{conversation_id}/stop")

    # ── server info ───────────────────────────────────────────────

    async def get_config(self) -> ServerConfig:
        """GET /api/config."""
        data = await self._get("/config")
        return ServerConfig.from_dict(data)

    async def get_models(self) -> list[dict[str, Any]]:
        """GET /api/models."""
        return await self._get("/models")

    # ── settings ──────────────────────────────────────────────────

    async def get_settings(self) -> dict[str, Any]:
        """GET /api/settings."""
        return await self._get("/settings")

    async def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """POST /api/settings."""
        return await self._post("/settings", json=settings)

    # ── secrets ───────────────────────────────────────────────────

    async def get_secrets(self) -> dict[str, Any]:
        """GET /api/secrets."""
        return await self._get("/secrets")

    async def set_secret(
        self,
        provider: str,
        token: str,
        *,
        host: str | None = None,
    ) -> dict[str, Any]:
        """POST /api/secrets."""
        payload: dict[str, Any] = {"provider": provider, "token": token}
        if host:
            payload["host"] = host
        return await self._post("/secrets", json=payload)

    # ── files / diffs ─────────────────────────────────────────────

    async def get_workspace_changes(self, conversation_id: str) -> list[dict[str, Any]]:
        """GET /api/git/changes?conversation_id=...."""
        data = await self._get(
            "/git/changes", params={"conversation_id": conversation_id}
        )
        return data if isinstance(data, list) else data.get("changes", [])

    async def get_file_diff(
        self,
        conversation_id: str,
        filepath: str,
    ) -> dict[str, Any]:
        """GET /api/git/diff?conversation_id=...&path=...."""
        return await self._get(
            "/git/diff",
            params={"conversation_id": conversation_id, "path": filepath},
        )

    # ── health ────────────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Quick liveness probe — GET /alive."""
        try:
            resp = await self._http.get("/alive")
            return resp.is_success
        except httpx.HTTPError:
            return False

    # =================================================================
    # Socket.IO — real-time event streaming
    # =================================================================

    def _register_sio_handlers(self) -> None:
        """Wire up Socket.IO client event handlers."""

        @self._sio.event
        async def connect() -> None:
            logger.info("Socket.IO connected")
            self._connect_event.set()

        @self._sio.event
        async def disconnect() -> None:
            logger.info("Socket.IO disconnected")
            self._connect_event.clear()

        @self._sio.on("forge_event")
        async def on_forge_event(data: dict[str, Any]) -> None:
            if self._event_callback:
                try:
                    await self._event_callback(data)
                except Exception:
                    logger.exception("Error in TUI event callback")

    async def join_conversation(
        self,
        conversation_id: str,
        *,
        on_event: EventCallback | None = None,
        latest_event_id: int = -1,
    ) -> None:
        """Connect to a conversation's live event stream via Socket.IO.

        If already connected to a different conversation, disconnects first.

        Args:
            conversation_id: Conversation to join.
            on_event: Async callback invoked for every ``forge_event``.
            latest_event_id: Resume from this event id (``-1`` = from start).
        """
        self._event_callback = on_event

        # Disconnect previous connection if any
        if self._sio.connected:
            await self._sio.disconnect()
            self._connect_event.clear()

        query = f"conversation_id={conversation_id}&latest_event_id={latest_event_id}"
        await self._sio.connect(
            self.base_url,
            socketio_path="/socket.io",
            transports=["websocket", "polling"],
            wait_timeout=15,
            headers={"Connection": "Upgrade"},
            auth={},
            namespaces=["/"],
        )
        # Socket.IO python client doesn't support query params in connect() directly —
        # we set them via the URL
        if not self._sio.connected:
            await self._sio.connect(
                f"{self.base_url}?{query}",
                socketio_path="/socket.io",
                transports=["websocket", "polling"],
                wait_timeout=15,
            )

        self._connected_conversation_id = conversation_id
        logger.info("Joined conversation %s via Socket.IO", conversation_id)

    async def leave_conversation(self) -> None:
        """Disconnect from the current conversation's event stream."""
        if self._sio.connected:
            await self._sio.disconnect()
        self._connected_conversation_id = None
        self._event_callback = None

    # ── sending actions over WS ───────────────────────────────────

    async def send_message(
        self,
        content: str,
        *,
        image_urls: list[str] | None = None,
    ) -> None:
        """Send a user chat message to the current conversation.

        This emits ``forge_user_action`` with the ``MessageAction`` payload,
        matching the same wire format the original web client sends.
        """
        if not self._sio.connected:
            msg = "Not connected to a conversation"
            raise RuntimeError(msg)

        timestamp = datetime.now(tz=timezone.utc).isoformat()
        payload = {
            "action": "message",
            "args": {
                "content": content,
                "image_urls": image_urls or [],
                "file_urls": [],
                "timestamp": timestamp,
            },
        }
        await self._sio.emit("forge_user_action", payload)

    async def send_confirmation(self, *, confirm: bool) -> None:
        """Send user confirmation (approve or reject) for a pending action.

        Args:
            confirm: ``True`` to approve, ``False`` to reject.
        """
        if not self._sio.connected:
            msg = "Not connected to a conversation"
            raise RuntimeError(msg)

        action = "user_confirmed" if confirm else "user_rejected"
        payload = {
            "action": action,
            "args": {},
        }
        await self._sio.emit("forge_user_action", payload)

    async def send_stop(self) -> None:
        """Request the agent to stop."""
        if self._connected_conversation_id:
            await self.stop_agent(self._connected_conversation_id)

    # ── convenience ───────────────────────────────────────────────

    @property
    def is_ws_connected(self) -> bool:
        """Whether the Socket.IO transport is up."""
        return self._sio.connected

    @property
    def current_conversation_id(self) -> str | None:
        return self._connected_conversation_id
