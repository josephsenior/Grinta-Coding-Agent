"""Centralised FastAPI exception handlers for the Forge server.

Call ``register_exception_handlers(app)`` from the application factory to
wire up all handlers.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.core.errors import (
    PersistenceError,
    ReplayError,
    SessionInvariantError,
)
from backend.core.errors import (
    AgentRuntimeUnavailableError,
    AgentStuckInLoopError,
    FunctionCallValidationError,
    LLMContextWindowExceedError,
    LLMMalformedActionError,
    LLMNoResponseError,
)
from backend.core.logger import forge_logger as logger
from backend.core.provider_types import AuthenticationError


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI application."""

    @app.exception_handler(SessionInvariantError)
    async def session_invariant_error_handler(
        request: Request, exc: SessionInvariantError
    ):
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=400, content=error_dict)

    @app.exception_handler(PersistenceError)
    async def persistence_error_handler(request: Request, exc: PersistenceError):
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=503, content=error_dict)

    @app.exception_handler(ReplayError)
    async def replay_error_handler(request: Request, exc: ReplayError):
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=503, content=error_dict)

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(request: Request, exc: AuthenticationError):
        """Handle authentication errors by returning 401 status."""
        from backend.api.utils.error_formatter import format_authentication_error

        user_error = format_authentication_error(
            exc, context={"path": request.url.path}
        )
        return JSONResponse(status_code=401, content=user_error.to_dict())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        """Handle request validation errors with user-friendly messages."""
        try:
            body = await request.body()
            body_str = body.decode("utf-8", errors="replace")[:500] if body else "empty"
            logger.error("Validation error for %s: %s", request.url.path, exc.errors())
            logger.error("Request body (truncated): %s", body_str)
        except Exception as e:
            logger.error("Could not read request body: %s", e)

        error_messages = []
        for err in exc.errors():
            field = " -> ".join(str(loc) for loc in err.get("loc", []))
            msg = err.get("msg", "Validation error")
            error_type = err.get("type", "unknown")
            error_messages.append(f"{field}: {msg} (type: {error_type})")

        return JSONResponse(
            status_code=400,
            content={
                "error": "Validation Error",
                "message": "Invalid request parameters",
                "details": error_messages,
                "path": request.url.path,
            },
        )

    @app.exception_handler(LLMNoResponseError)
    async def llm_no_response_handler(request: Request, exc: LLMNoResponseError):
        """Handle LLM no response errors."""
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=503, content=error_dict)

    @app.exception_handler(LLMContextWindowExceedError)
    async def context_window_handler(
        request: Request, exc: LLMContextWindowExceedError
    ):
        """Handle context window exceeded."""
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=400, content=error_dict)

    @app.exception_handler(AgentStuckInLoopError)
    async def agent_stuck_handler(request: Request, exc: AgentStuckInLoopError):
        """Handle agent stuck in loop."""
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=409, content=error_dict)

    @app.exception_handler(AgentRuntimeUnavailableError)
    async def runtime_unavailable_handler(
        request: Request, exc: AgentRuntimeUnavailableError
    ):
        """Handle runtime unavailable."""
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=503, content=error_dict)

    @app.exception_handler(FunctionCallValidationError)
    async def function_call_error_handler(
        request: Request, exc: FunctionCallValidationError
    ):
        """Handle function call errors."""
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=422, content=error_dict)

    @app.exception_handler(LLMMalformedActionError)
    async def malformed_action_handler(request: Request, exc: LLMMalformedActionError):
        """Handle malformed action errors."""
        from backend.api.utils.error_formatter import format_error_for_user

        error_dict = format_error_for_user(exc, context={"path": request.url.path})
        return JSONResponse(status_code=422, content=error_dict)

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        """Handle all unhandled exceptions — safety net."""
        from backend.api.utils.error_formatter import safe_format_error

        logger.exception("Unhandled exception: %s", type(exc).__name__)
        error_dict = safe_format_error(exc, context={"path": request.url.path})
        return JSONResponse(status_code=500, content=error_dict)
