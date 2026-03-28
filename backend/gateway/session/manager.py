"""Global session registry used by API routes (e.g. debug introspection)."""

from __future__ import annotations

from backend.gateway.session.session_manager import SessionManager

session_manager = SessionManager()
