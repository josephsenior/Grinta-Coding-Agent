"""Async client for the Forge backend — REST (httpx) + WebSocket (Socket.IO).

This module is the *only* place the TUI touches the network.  Every other
TUI component talks through :class:`ForgeClient`.

Usage::

    client = ForgeClient("http://localhost:3001")
    await client.connect()
    convos = await client.list_conversations()
    c = await client.create_conversation("Fix the login bug")
    await client.join_conversation(c["conversation_id"], on_event=my_handler)
    await client.send_message("Please also add tests")
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import socketio  # type: ignore[import-untyped]

logger = logging.getLogger("forge.tui.client")

# ---------------------------------------------------------------------------
# Resilience configuration
# ---------------------------------------------------------------------------
_RECONNECT_ATTEMPTS = 0  # 0 = unlimited
_RECONNECT_DELAY_MIN = 1.0  # seconds — initial backoff
_RECONNECT_DELAY_MAX = 30.0  # seconds — ceiling
_HEARTBEAT_INTERVAL = 25  # seconds between client-side pings
_OFFLINE_QUEUE_MAX = 200  # max buffered actions while disconnected

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
    tags: tuple[str, ...] = ()
    project: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationInfo:
        return cls(
            conversation_id=data.get("conversation_id", ""),
            title=data.get("title", data.get("conversation_id", "Untitled")),
            status=data.get("status", data.get("conversation_status", "unknown")),
            created_at=data.get("created_at", ""),
            last_updated_at=data.get("last_updated_at", data.get("updated_at", "")),
            tags=tuple(data.get("tags", [])),
            project=data.get("project", ""),
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

    base_url: str = "http://localhost:3001"

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
            base_url=f"{self.base_url}/api/v1",
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
        self._sio = socketio.AsyncClient(
            logger=False,
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=_RECONNECT_ATTEMPTS,
            reconnection_delay=_RECONNECT_DELAY_MIN,
            reconnection_delay_max=_RECONNECT_DELAY_MAX,
        )
        # Offline message queue — actions buffered while disconnected
        self._offline_queue: deque[tuple[str, dict[str, Any]]] = deque(
            maxlen=_OFFLINE_QUEUE_MAX,
        )
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._register_sio_handlers()

    # ── lifecycle ─────────────────────────────────────────────────

    async def close(self) -> None:
        """Tear down HTTP + WS connections."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._sio.connected:
            await self._sio.disconnect()
        await self._http.aclose()

    # ── REST helpers ──────────────────────────────────────────────

    async def _get(self, path: str, **kwargs: Any) -> Any:
        resp = await self._http.get(path, **kwargs)
        self._raise_for_status(resp)
        return resp.json()

    async def _post(self, path: str, **kwargs: Any) -> Any:
        resp = await self._http.post(path, **kwargs)
        self._raise_for_status(resp)
        return resp.json()

    async def _delete(self, path: str) -> bool:
        resp = await self._http.delete(path)
        return resp.is_success

    async def _patch(self, path: str, **kwargs: Any) -> Any:
        resp = await self._http.patch(path, **kwargs)
        self._raise_for_status(resp)
        return resp.json()

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        """Raise an error with the server's own detail message when possible."""
        status_code = int(getattr(resp, "status_code", 0) or 0)
        # Mirror httpx.Response.is_success semantics (2xx only)
        if 200 <= status_code < 300:
            return
        detail: str = ""
        try:
            body = resp.json()
            detail = (
                body.get("detail") or body.get("message") or body.get("error") or ""
            )
            if isinstance(detail, list):  # FastAPI validation errors
                detail = "; ".join(str(e.get("msg", e)) for e in detail)
        except Exception:
            detail = getattr(resp, "text", "") or getattr(resp, "reason_phrase", "") or ""
        code = status_code
        prefix = {
            400: "Bad request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not found",
            422: "Validation error",
            500: "Server error",
            503: "Service unavailable",
        }.get(code, f"HTTP {code}")
        reason_phrase = getattr(resp, "reason_phrase", "")
        msg = f"{prefix}: {detail}" if detail else f"HTTP {code} {reason_phrase}"
        request = cast(httpx.Request, getattr(resp, "request", None))
        raise httpx.HTTPStatusError(msg, request=request, response=resp)

    # ── conversations ─────────────────────────────────────────────

    async def list_conversations(
        self,
        page_id: str | None = None,
        limit: int = 20,
    ) -> list[ConversationInfo]:
        """GET /api/conversations → list of conversations."""
        data = await self._get(
            "/conversations",
            params={"page_id": page_id, "limit": limit},
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

        Automatically prepends the content of ``.forge/context.md`` (if it
        exists) to ``conversation_instructions`` so the agent always has the
        project context without the user having to paste it.

        Returns the raw response dict (contains ``conversation_id``).
        """
        # Inject local project memory if available
        try:
            from backend.core.workspace_context import read_project_memory

            memory = read_project_memory()
            if memory:
                if conversation_instructions:
                    conversation_instructions = (
                        memory + "\n\n---\n\n" + conversation_instructions
                    )
                else:
                    conversation_instructions = memory
        except Exception:
            pass  # Never fail conversation creation over a missing context file

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
        return await self._post(f"/conversations/{conversation_id}/start", json={"providers_set": []})

    async def stop_agent(self, conversation_id: str) -> dict[str, Any]:
        """POST /api/conversations/{id}/stop."""
        return await self._post(f"/conversations/{conversation_id}/stop")

    # ── server info ───────────────────────────────────────────────

    async def get_config(self) -> ServerConfig:
        """GET /api/config."""
        data = await self._get("/config")
        return ServerConfig.from_dict(data)

    async def get_models(self) -> list[dict[str, Any]]:
        """GET /api/v1/options/models."""
        models = await self._get("/options/models")
        return [
            {"id": m, "name": m, "model": m} if isinstance(m, str) else m
            for m in (models or [])
        ]

    # ── settings ──────────────────────────────────────────────────

    async def get_settings(self) -> dict[str, Any]:
        """GET /api/settings."""
        return await self._get("/settings")

    async def save_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """POST /api/settings."""
        return await self._post("/settings", json=settings)

    async def get_budget_limits(self) -> dict[str, float | None]:
        """Return session and daily budget limits from server config.

        Returns a dict with keys ``session_limit`` and ``daily_limit``
        (both may be None if not configured).
        """
        try:
            data = await self._get("/options/config")
            return {
                "session_limit": data.get("max_budget_per_session") or None,
                "daily_limit": data.get("max_budget_per_day") or None,
            }
        except Exception:
            # Fall back to reading config file directly when server is unavailable
            try:
                import json
                from pathlib import Path

                cfg_path = Path.cwd() / "settings.json"
                if cfg_path.exists():
                    with cfg_path.open(encoding="utf-8") as fh:
                        cfg = json.load(fh)
                    core = cfg
                    return {
                        "session_limit": core.get("max_budget_per_session") or None,
                        "daily_limit": core.get("max_budget_per_day") or None,
                    }
            except Exception:
                pass
            return {"session_limit": None, "daily_limit": None}


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
        """Quick liveness probe \u2014 GET /alive."""
        try:
            resp = await self._http.get("/alive")
            print("HEALTH STATUS CODE:", resp.status_code)
            return resp.is_success
        except Exception as e:
            print("HEALTHCHECK HTTPX EXCEPTION:", type(e), e)
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
            # Auto-rejoin the conversation we were in before disconnect
            cid = self._connected_conversation_id
            if cid:
                logger.info("Reconnected — auto-rejoining conversation %s", cid)
                try:
                    await self._sio.emit(
                        "rejoin",
                        {"conversation_id": cid},
                    )
                except Exception:
                    logger.warning(
                        "Auto-rejoin emit failed for %s",
                        cid,
                        exc_info=True,
                    )
            # Flush offline queue
            await self._flush_offline_queue()
            # Start heartbeat monitor
            self._start_heartbeat()

        @self._sio.event
        async def disconnect() -> None:
            logger.info("Socket.IO disconnected")
            self._connect_event.clear()
            self._stop_heartbeat()

        @self._sio.on("forge_event")
        async def on_forge_event(data: dict[str, Any]) -> None:
            if self._event_callback:
                try:
                    await self._event_callback(data)
                except Exception:
                    logger.exception("Error in TUI event callback")

    # ── heartbeat ─────────────────────────────────────────────────

    def _start_heartbeat(self) -> None:
        """Start a periodic heartbeat ping to detect stale connections early."""
        self._stop_heartbeat()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._heartbeat_task = loop.create_task(
            self._heartbeat_loop(),
            name="forge-ws-heartbeat",
        )

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """Send a lightweight ping at ``_HEARTBEAT_INTERVAL``."""
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                if self._sio.connected:
                    try:
                        await self._sio.emit("ping", {})
                    except Exception:
                        logger.debug("Heartbeat ping failed", exc_info=True)
        except asyncio.CancelledError:
            pass

    # ── offline queue ─────────────────────────────────────────────

    def _buffer_action(self, event: str, payload: dict[str, Any]) -> None:
        """Buffer an action for later delivery when reconnected."""
        self._offline_queue.append((event, payload))
        logger.debug(
            "Buffered offline action (queue depth: %d)",
            len(self._offline_queue),
        )

    async def _flush_offline_queue(self) -> None:
        """Drain and deliver any buffered offline actions."""
        if not self._offline_queue:
            return
        flushed = 0
        while self._offline_queue and self._sio.connected:
            event, payload = self._offline_queue.popleft()
            try:
                await self._sio.emit(event, payload)
                flushed += 1
            except Exception:
                # Re-queue at the front for next reconnect
                self._offline_queue.appendleft((event, payload))
                logger.warning("Failed to flush offline action; re-queued")
                break
        if flushed:
            logger.info("Flushed %d buffered offline actions", flushed)

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
        # Socket.IO python client doesn't support query params in connect() directly —
        # we set them via the URL. We include common headers for robustness.
        url = f"{self.base_url}?{query}"
        logger.info("Connecting to Socket.IO at %s", url)

        try:
            await self._sio.connect(
                url,
                socketio_path="/socket.io",
                transports=["websocket", "polling"],
                wait_timeout=15,
                namespaces=["/"],
            )
        except Exception as e:
            logger.error("Failed to connect to Socket.IO: %s", e)
            # Fallback to polling if websocket fails and we haven't tried yet
            if not self._sio.connected:
                await self._sio.connect(
                    url,
                    socketio_path="/socket.io",
                    transports=["polling"],
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

        If the Socket.IO transport is down the action is buffered and will be
        delivered automatically when the connection is restored.
        """
        timestamp = datetime.now(tz=UTC).isoformat()
        payload = {
            "action": "message",
            "args": {
                "content": content,
                "image_urls": image_urls or [],
                "file_urls": [],
                "timestamp": timestamp,
            },
        }
        if self._sio.connected:
            await self._sio.emit("forge_user_action", payload)
        else:
            self._buffer_action("forge_user_action", payload)

    async def send_confirmation(self, *, confirm: bool) -> None:
        """Send user confirmation (approve or reject) for a pending action.

        Args:
            confirm: ``True`` to approve, ``False`` to reject.
        """
        action = "user_confirmed" if confirm else "user_rejected"
        payload = {
            "action": action,
            "args": {},
        }
        if self._sio.connected:
            await self._sio.emit("forge_user_action", payload)
        else:
            self._buffer_action("forge_user_action", payload)

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
