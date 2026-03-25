"""Routes for file browsing, reading, and uploading within conversations."""

from __future__ import annotations

import contextlib
import os
from pathlib import Path as PathLib
from typing import TYPE_CHECKING, Annotated, Any, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field
from starlette.background import BackgroundTask

from backend.core.errors import AgentRuntimeUnavailableError
from backend.core.logger import forge_logger as logger
from backend.events.action import FileReadAction
from backend.events.action.files import FileWriteAction
from backend.events.observation import ErrorObservation, FileReadObservation
from backend.runtime.utils.git_changes import get_git_changes
from backend.api.route_dependencies import get_dependencies
from backend.core.constants import FILES_TO_IGNORE
from backend.api.files import POSTUploadFilesModel
from backend.api.utils import get_conversation, get_conversation_store
from backend.api.utils.responses import error
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from typing import Protocol

    from backend.api.session.conversation import ServerConversation

    class RuntimeFileOps(Protocol):
        """Protocol describing runtime operations used by file routes."""

        config: Any  # pragma: no cover - protocol attribute

        def list_files(
            self, path: str | None = None
        ) -> list[str]:  # pragma: no cover - protocol method
            ...

        def copy_from(
            self, path: str
        ) -> str | os.PathLike[str]:  # pragma: no cover - protocol method
            ...

        def get_git_diff(
            self, path: str, cwd: str
        ) -> dict[str, Any]:  # pragma: no cover - protocol method
            ...

        def run_action(self, action: Any) -> Any:  # pragma: no cover - protocol method
            ...


sub_router = APIRouter(
    prefix="/api/v1/conversations/{conversation_id}/files",
    dependencies=get_dependencies(),
    tags=["files"],
)


def _unlink_path(path: PathLib) -> None:
    """Background helper to remove temporary archive files."""
    path.unlink(missing_ok=True)


async def _ensure_runtime_ready(conversation: ServerConversation) -> bool:
    """Ensure runtime is ready, waiting if necessary."""
    if conversation.runtime:
        return True

    logger.warning(
        "list-files request for conversation %s received before runtime ready.",
        conversation.sid,
    )
    import asyncio

    max_wait = 5
    wait_interval = 0.2
    waited = 0.0
    while waited < max_wait and not conversation.runtime:
        await asyncio.sleep(wait_interval)
        waited += wait_interval
        if hasattr(conversation, "runtime") and conversation.runtime:
            logger.info(
                "Runtime for conversation %s became available after %ss",
                conversation.sid,
                waited,
            )
            return True

    logger.error(
        "list-files request: runtime for conversation %s still not ready after %ss.",
        conversation.sid,
        max_wait,
    )
    return False


def _get_runtime_not_ready_error():
    """Return error when runtime is not ready."""
    return error(
        message=(
            "⏳ Workspace is still starting up\n\n"
            "Your development environment is being initialized. This usually takes a few seconds.\n\n"
            "**If this persists, the local runtime may have failed to initialize.**\n\n"
            "**What you can do:**\n"
            "• Wait a moment and try again\n"
            "• Refresh the page\n"
            "• Check the backend logs for runtime initialization errors\n"
            "• Try starting a new conversation\n\n"
            "**Note:** Check the backend console for detailed error messages about why the runtime failed to initialize."
        ),
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_code="RUNTIME_NOT_READY",
    )


def _get_runtime_connection_error():
    """Return error when runtime is running but not responding."""
    return error(
        message=(
            "⚠️ Workspace connection issue\n\n"
            "The workspace runtime is running but not responding to requests.\n\n"
            "**What you can do:**\n"
            "• Wait 30 seconds and try again (the server may still be starting)\n"
            "• Refresh the page\n"
            "• Start a new conversation if the problem persists\n\n"
            "**Note:** This usually resolves itself as the workspace finishes initializing."
        ),
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_code="RUNTIME_CONNECTION_ERROR",
    )


def _get_runtime_unavailable_error():
    """Return error when runtime is not running."""
    return error(
        message=(
            "❌ Workspace unavailable\n\n"
            "The workspace container is not running or has stopped.\n\n"
            "**What you can do:**\n"
            "• Start a new conversation to create a fresh workspace\n"
            "• Check if the container crashed (check logs)\n"
            "• Wait a moment and refresh the page\n\n"
            "**Note:** Your conversation data is saved, but you'll need a new workspace."
        ),
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        error_code="RUNTIME_UNAVAILABLE",
    )


def _get_runtime_timeout_error():
    """Return error when runtime request times out."""
    return error(
        message=(
            "⏱️ Request timeout\n\n"
            "The workspace took too long to respond when listing files.\n\n"
            "**What you can do:**\n"
            "• Wait a moment and try again\n"
            "• The workspace may be under heavy load\n"
            "• Try refreshing the page\n\n"
            "**Note:** This is usually temporary."
        ),
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        error_code="RUNTIME_TIMEOUT",
    )


def _validate_list_files_path(
    path: str | None, workspace_root: str
) -> tuple[str | None, Any | None]:
    """Validate path for list_files. Returns (validated_path_str, error_response).

    If validation fails, returns (path, error_response). If path is None, returns (None, None).
    """
    if path is None:
        return None, None
    try:
        from backend.core.type_safety.path_validation import (
            PathValidationError,
            SafePath,
        )

        safe_path = SafePath.validate(
            str(path), workspace_root=workspace_root, must_be_relative=True
        )
        return safe_path.relative_to_workspace(), None
    except PathValidationError as e:
        logger.warning("Invalid path provided to list_files: %s - %s", path, e.message)
        return path, error(
            message=f"Invalid path: {e.message}",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_PATH",
        )


async def _fetch_file_list_from_runtime(
    runtime: Any, path: str | None, *, recursive: bool = False
) -> tuple[list[str] | None, Any | None]:
    """Call runtime.list_files and handle errors. Returns (file_list, error_response)."""
    try:
        file_list = await call_sync_from_async(
            runtime.list_files, path, recursive
        )
        return file_list, None
    except (httpx.ConnectError, ConnectionRefusedError) as e:
        logger.error("Runtime unavailable when listing files: %s", e, exc_info=True)
        container_status = "unknown"
        if hasattr(runtime, "container") and runtime.container is not None:
            with contextlib.suppress(Exception):
                runtime.container.reload()
                container_status = runtime.container.status
        if container_status == "running":
            return None, _get_runtime_connection_error()
        return None, _get_runtime_unavailable_error()
    except httpx.TimeoutException as e:
        logger.error("Timeout listing files: %s", e, exc_info=True)
        return None, _get_runtime_timeout_error()
    except Exception as e:
        logger.error(
            "Unexpected error listing files: %s (type: %s)",
            e,
            type(e).__name__,
            exc_info=True,
        )
        if isinstance(e, AgentRuntimeUnavailableError):
            return None, error(
                message=(
                    "❌ Workspace error\n\n"
                    f"An error occurred while listing files: {e}\n\n"
                    "**What you can do:**\n"
                    "• Try again in a moment\n"
                    "• Start a new conversation if the problem persists\n"
                    "• Check the workspace status\n\n"
                    "**Technical details:** Runtime unavailable"
                ),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                error_code="LIST_FILES_ERROR",
            )
        return None, error(
            message=(
                "❌ Workspace unavailable\n\n"
                "Unable to connect to the workspace. The container may have stopped or crashed.\n\n"
                "**What you can do:**\n"
                "• Start a new conversation to create a fresh workspace\n"
                "• Wait a moment and refresh the page\n"
                "• Check if the workspace is still initializing\n\n"
                "**Note:** Your conversation data is saved."
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="RUNTIME_UNAVAILABLE",
        )


def _apply_path_prefix_and_filter(
    file_list: list[str], path: str | None
) -> list[str]:
    """Prefix files with path if provided, then filter out ignored files."""
    if path is not None:
        file_list = [os.path.join(str(path), f) for f in file_list]
    return [f for f in file_list if f not in FILES_TO_IGNORE]


@sub_router.get(
    "/list-files",
    response_model=None,
    responses={
        200: {"description": "List of file paths"},
        404: {"description": "Runtime not initialized"},
        500: {"description": "Error listing or filtering files"},
    },
)
async def list_files(
    path: str | None = Query(None, description="Optional path to list files from"),
    recursive: bool = Query(
        False,
        description="If true, list all files under path (or workspace root) recursively",
    ),
    conversation: ServerConversation = Depends(get_conversation),
) -> Any:
    """List files in the specified path."""
    if not await _ensure_runtime_ready(conversation):
        return _get_runtime_not_ready_error()

    runtime = cast("RuntimeFileOps", conversation.runtime)
    workspace_root = runtime.config.workspace_mount_path_in_runtime

    validated_path, path_error = _validate_list_files_path(path, workspace_root)
    if path_error is not None:
        return path_error
    path = validated_path

    try:
        if hasattr(runtime, "check_if_alive"):
            await call_sync_from_async(runtime.check_if_alive)
    except Exception as health_check_error:
        logger.warning(
            "Runtime health check failed before listing files: %s", health_check_error
        )

    file_list, fetch_error = await _fetch_file_list_from_runtime(
        runtime, path, recursive=recursive
    )
    if fetch_error is not None:
        return fetch_error

    return _apply_path_prefix_and_filter(file_list or [], path)


@sub_router.get(
    "/select-file",
    response_model=None,
    responses={
        200: {"description": "File content returned as JSON", "model": dict[str, str]},
        500: {"description": "Error opening file", "model": dict},
        415: {"description": "Unsupported media type", "model": dict},
    },
)
async def select_file(
    file: Annotated[str, Field(..., min_length=1, description="File path to retrieve")],
    conversation: ServerConversation = Depends(get_conversation),
) -> Any:
    """Retrieve the content of a specified file.

    To select a file:
    ```sh
    curl http://localhost:3000/api/conversations/{conversation_id}select-file?file=<file_path>
    ```

    Args:
        file (str): The path of the file to be retrieved.
            Expect path to be absolute inside the runtime.
        conversation (ServerConversation): The conversation object containing runtime information.

    Returns:
        dict: A dictionary containing the file content.

    Raises:
        HTTPException: If there's an error opening the file.

    """
    # Check if runtime is ready before accessing it
    if not conversation.runtime:
        logger.warning(
            "select-file request received before runtime ready for file: %s", file
        )
        return error(
            message="Runtime not ready yet, please try again",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="RUNTIME_NOT_READY",
        )

    runtime = cast("RuntimeFileOps", conversation.runtime)
    workspace_root = runtime.config.workspace_mount_path_in_runtime

    # Use SafePath for production-grade path validation with workspace boundaries
    try:
        from backend.core.type_safety.path_validation import (
            PathValidationError,
            SafePath,
        )

        # Validate and sanitize path using SafePath
        safe_path = SafePath.validate(
            file,
            workspace_root=workspace_root,
            must_be_relative=True,  # Enforce workspace boundaries
        )
        file = str(safe_path.path)
    except PathValidationError as e:
        logger.warning("Invalid file path provided: %s - %s", file, e.message)
        return error(
            message=f"Invalid file path: {e.message}",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_FILE_PATH",
        )
    read_action = FileReadAction(file)
    try:
        observation = await call_sync_from_async(runtime.run_action, read_action)
    except (httpx.ConnectError, ConnectionRefusedError) as e:
        # Runtime container is unavailable (crashed or stopped)
        logger.error("Runtime container unavailable when opening file %s: %s", file, e)
        return error(
            message="Runtime container is unavailable. Please start a new conversation.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="RUNTIME_UNAVAILABLE",
        )
    except AgentRuntimeUnavailableError as e:
        logger.error("Error opening file %s: %s", file, e)
        return error(
            message=f"Error opening file: {e}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FILE_OPEN_ERROR",
        )
    if isinstance(observation, FileReadObservation):
        content = observation.content
        return JSONResponse(content={"code": content})
    if isinstance(observation, ErrorObservation):
        logger.error("Error opening file %s: %s", file, observation)
        if "ERROR_BINARY_FILE" in observation.message:
            return error(
                message=f"Unable to open binary file: {file}",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                error_code="BINARY_FILE_ERROR",
            )
        return error(
            message=f"Error opening file: {observation}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FILE_OBSERVATION_ERROR",
        )
    return error(
        message=f"Unexpected observation type: {type(observation)}",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code="UNEXPECTED_OBSERVATION",
    )


@sub_router.get(
    "/zip-directory",
    response_model=None,
    responses={
        200: {"description": "Zipped workspace returned as FileResponse"},
        500: {"description": "Error zipping workspace", "model": dict},
    },
)
def zip_current_workspace(
    conversation: ServerConversation = Depends(get_conversation),
) -> Any:
    """Zip the current workspace and return it as a downloadable file.

    Args:
        conversation (ServerConversation): The conversation object containing runtime information.

    Returns:
        FileResponse: A file response containing the zipped workspace.
        JSONResponse: An error response if zipping fails.

    """
    if not conversation.runtime:
        logger.warning("zip_current_workspace request received before runtime ready")
        return error(
            message="Runtime not ready",
            status_code=503,
            error_code="RUNTIME_NOT_READY",
        )
    try:
        logger.debug("Zipping workspace")
        runtime = cast("RuntimeFileOps", conversation.runtime)
        path = runtime.config.workspace_mount_path_in_runtime
        try:
            zip_file_path = PathLib(runtime.copy_from(path))
        except AgentRuntimeUnavailableError as e:
            logger.error("Error zipping workspace: %s", e)
            return error(
                message=f"Error zipping workspace: {e}",
                status_code=500,
                error_code="ZIP_ERROR",
            )
        return FileResponse(
            path=str(zip_file_path),
            filename="workspace.zip",
            media_type="application/zip",
            background=BackgroundTask(_unlink_path, zip_file_path),
        )
    except Exception as e:
        logger.error("Error zipping workspace: %s", e)
        raise HTTPException(status_code=500, detail="Failed to zip workspace") from e


@sub_router.get(
    "/git/changes",
    response_model=None,
    responses={
        200: {"description": "List of git changes (empty if not a repo or no changes)"},
        503: {"description": "Runtime not ready"},
        500: {"description": "Error getting changes"},
    },
)
async def git_changes(
    conversation_id: str,
    conversation: ServerConversation = Depends(get_conversation),
) -> Any:
    """Get list of git-tracked file changes in the workspace.

    Retrieves the conversation's runtime and queries it for modified files
    compared to the git repository. Returns empty list if not a git repository
    or if git is unavailable in the runtime container.

    Uses the same authenticated user as other file routes (not a hard-coded
    ``dev-user``) so OSS / multi-user sessions can load the CHANGES panel.

    Args:
        conversation_id: Conversation identifier to query runtime

    Returns:
        list[dict[str, str]]: List of changed file dictionaries with metadata, or
        JSONResponse with error details if operation fails

    Raises:
        HTTPException: If runtime is unavailable or operation fails

    Example:
        GET /api/conversations/{conversation_id}/files/git/changes
        Response: [{"path": "src/main.py", "status": "modified"}, ...]

    """
    if not conversation.runtime:
        return JSONResponse(
            content={"error": "Runtime not ready"}, status_code=503
        )

    runtime = cast("RuntimeFileOps", conversation.runtime)
    cwd = runtime.config.workspace_mount_path_in_runtime
    logger.info("Getting git changes in %s", cwd)

    # Check if the workspace directory exists
    if not os.path.exists(cwd):
        logger.warning("Workspace directory %s does not exist", cwd)
        return JSONResponse(status_code=200, content=[])

    try:
        changes = await call_sync_from_async(get_git_changes, cwd)
        if changes is None:
            return JSONResponse(status_code=200, content=[])
        return changes
    except FileNotFoundError as e:
        if "git" in str(e):
            logger.warning(
                "Git not available in container, returning empty changes list"
            )
            return JSONResponse(status_code=200, content=[])
        raise
    except AgentRuntimeUnavailableError as e:
        logger.error("Runtime unavailable: %s", e)
        return JSONResponse(
            status_code=500, content={"error": f"Error getting changes: {e}"}
        )
    except Exception as e:
        logger.error("Error getting changes: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


@sub_router.get(
    "/git/diff",
    response_model=None,
    responses={
        200: {"description": "Git diff data"},
        500: {"description": "Error getting diff"},
    },
)
async def git_diff(
    path: Annotated[
        str, Field(..., min_length=1, description="Path to get git diff for")
    ],
    conversation_store: Any = Depends(get_conversation_store),
    conversation: ServerConversation = Depends(get_conversation),
) -> Any:
    """Get git diff for a specific path in the workspace.

    Args:
        path (str): The path to get the git diff for.
        conversation_store (Any): The conversation store for persistence.
        conversation (ServerConversation): The conversation object containing runtime information.

    Returns:
        dict[str, Any]: A dictionary containing the git diff information.
        JSONResponse: An error response if git operations fail.

    """
    # Check if runtime is ready
    if not conversation.runtime:
        logger.warning(
            "git_diff request received before runtime ready for path: %s", path
        )
        return error(
            message="Runtime not ready yet, please try again",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="RUNTIME_NOT_READY",
        )

    runtime = cast("RuntimeFileOps", conversation.runtime)
    workspace_root = runtime.config.workspace_mount_path_in_runtime

    # Use SafePath for production-grade path validation with workspace boundaries
    try:
        from backend.core.type_safety.path_validation import (
            PathValidationError,
            SafePath,
        )

        # Validate and sanitize path using SafePath
        safe_path = SafePath.validate(
            path.strip(),
            workspace_root=workspace_root,
            must_be_relative=True,  # Enforce workspace boundaries
        )
        sanitized_path = safe_path.relative_to_workspace()
    except PathValidationError as e:
        logger.warning(
            "Invalid file path provided to git_diff: %s - %s", path, e.message
        )
        return error(
            message=f"Invalid file path: {e.message}",
            status_code=status.HTTP_400_BAD_REQUEST,
            error_code="INVALID_FILE_PATH",
        )

    cwd = workspace_root
    try:
        return await call_sync_from_async(runtime.get_git_diff, sanitized_path, cwd)
    except AgentRuntimeUnavailableError as e:
        logger.error("Error getting diff: %s", e)
        return error(
            message=f"Error getting diff: {e}",
            status_code=500,
            error_code="GIT_DIFF_ERROR",
        )


@sub_router.post("/upload-files", response_model=POSTUploadFilesModel)
async def upload_files(
    files: list[UploadFile],
    conversation: ServerConversation = Depends(get_conversation),
):
    """Upload files to the workspace.

    Args:
        files (list[UploadFile]): The list of files to upload.
        conversation (ServerConversation): The conversation object containing runtime information.

    Returns:
        JSONResponse: A response containing lists of uploaded and skipped files.

    """
    uploaded_files = []
    skipped_files = []

    # Check if runtime is ready
    if not conversation.runtime:
        return error(
            message="Runtime not ready yet, please try again",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="RUNTIME_NOT_READY",
        )

    runtime = cast("RuntimeFileOps", conversation.runtime)
    workspace_root = runtime.config.workspace_mount_path_in_runtime

    for file in files:
        try:
            # Validate filename is not empty
            if not file.filename:
                raise ValueError("Filename cannot be empty")

            # Use SafePath for production-grade path validation with workspace boundaries
            from backend.core.type_safety.path_validation import (
                PathValidationError,
                SafePath,
            )

            # Validate and sanitize filename using SafePath
            safe_path = SafePath.validate(
                str(file.filename),
                workspace_root=workspace_root,
                must_be_relative=True,  # Enforce workspace boundaries
            )
            sanitized_filename = safe_path.relative_to_workspace()
        except (ValueError, PathValidationError) as e:
            error_message = e.message if isinstance(e, PathValidationError) else str(e)
            skipped_files.append(
                {"name": file.filename or "<unknown>", "reason": error_message}
            )
            continue

        file_path = os.path.join(
            runtime.config.workspace_mount_path_in_runtime, sanitized_filename
        )
        try:
            file_content = await file.read()
            write_action = FileWriteAction(
                path=file_path, content=file_content.decode("utf-8", errors="replace")
            )
            await call_sync_from_async(runtime.run_action, write_action)
            uploaded_files.append(file_path)
        except Exception as e:
            skipped_files.append({"name": file.filename, "reason": str(e)})
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"uploaded_files": uploaded_files, "skipped_files": skipped_files},
    )

