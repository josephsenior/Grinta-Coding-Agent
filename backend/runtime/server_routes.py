"""FastAPI route handlers for the runtime action execution server.

Extracted from action_execution_server.py to separate HTTP route definitions
from the ActionExecutor class. Contains: exception handlers, auth middleware,
and all REST endpoints (execute_action, upload, download, list_files, etc.).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from typing import TYPE_CHECKING, Any
from zipfile import ZipFile

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.core.config.mcp_config import MCPStdioServerConfig
from backend.core.logger import forge_logger as logger
from backend.events.action import Action
from backend.events.serialization import event_from_dict, event_to_dict
from backend.runtime.utils.system_stats import (
    get_system_stats,
    update_last_execution_time,
)

if TYPE_CHECKING:
    pass


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception occurred:")
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred. Please try again later."},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.error("HTTP exception occurred: %s", exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        logger.error("Validation error occurred: %s", exc)
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Invalid request parameters",
                "errors": str(exc.errors()),
            },
        )


def register_routes(
    app: FastAPI,
    get_client: Any,
    get_mcp_proxy: Any,
) -> None:
    """Register all REST endpoint routes on the FastAPI app.

    Args:
        app: FastAPI application
        get_client: Callable that returns the current ActionExecutor instance
        get_mcp_proxy: Callable that returns the current MCPProxyManager instance
    """

    @app.get("/server_info")
    async def get_server_info():
        client = get_client()
        assert client is not None
        current_time = time.time()
        uptime = current_time - client.start_time
        idle_time = current_time - client.last_execution_time
        response = {
            "uptime": uptime,
            "idle_time": idle_time,
            "resources": get_system_stats(),
        }
        logger.info("Server info endpoint response: %s", response)
        return response

    @app.post("/execute_action")
    async def execute_action_route(action_request: Any):
        client = get_client()
        assert client is not None
        try:
            action = event_from_dict(action_request.event)
            if not isinstance(action, Action):
                raise HTTPException(status_code=400, detail="Invalid action type")
            client.last_execution_time = time.time()
            observation = await client.run_action(action)
            return event_to_dict(observation)
        except Exception as e:
            logger.error("Error while running /execute_action: %s", str(e))
            raise HTTPException(status_code=500, detail=traceback.format_exc()) from e
        finally:
            update_last_execution_time()

    @app.post("/update_mcp_server")
    async def update_mcp_server(request: Request):
        is_windows = sys.platform == "win32"
        mcp_proxy_manager = get_mcp_proxy()
        if is_windows:
            logger.info("MCP server update skipped on Windows")
            return JSONResponse(
                status_code=200,
                content={
                    "detail": "MCP server update skipped (MCP is disabled on Windows)",
                    "router_error_log": "",
                },
            )
        if mcp_proxy_manager is None:
            raise HTTPException(
                status_code=500, detail="MCP Proxy Manager is not initialized"
            )
        mcp_tools_to_sync = await request.json()
        if not isinstance(mcp_tools_to_sync, list):
            raise HTTPException(
                status_code=400, detail="Request must be a list of MCP tools to sync"
            )
        logger.info(
            "Updating MCP server with tools: %s",
            json.dumps(mcp_tools_to_sync, indent=2),
        )
        mcp_tools_to_sync = [MCPStdioServerConfig(**tool) for tool in mcp_tools_to_sync]
        try:
            await mcp_proxy_manager.update_and_remount(app, mcp_tools_to_sync, ["*"])
            logger.info("MCP Proxy Manager updated and remounted successfully")
            router_error_log = ""
        except Exception as e:
            logger.error("Error updating MCP Proxy Manager: %s", e, exc_info=True)
            router_error_log = str(e)
        return JSONResponse(
            status_code=200,
            content={
                "detail": "MCP server updated successfully",
                "router_error_log": router_error_log,
            },
        )

    @app.post("/upload_file")
    def upload_file(
        file: UploadFile, destination: str = "/", recursive: bool = False
    ):
        client = get_client()
        assert client is not None
        try:
            filename = file.filename
            if not filename:
                raise HTTPException(
                    status_code=400, detail="Uploaded file must have a filename"
                )
            if not os.path.isabs(destination):
                raise HTTPException(
                    status_code=400, detail="Destination must be an absolute path"
                )
            full_dest_path = destination
            if not os.path.exists(full_dest_path):
                os.makedirs(full_dest_path, exist_ok=True)
            if recursive or (not recursive and filename.endswith(".zip")):
                if not filename.endswith(".zip"):
                    raise HTTPException(
                        status_code=400, detail="Recursive uploads must be zip files"
                    )
                zip_path = os.path.join(full_dest_path, filename)
                with open(zip_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
                shutil.unpack_archive(zip_path, full_dest_path)
                os.remove(zip_path)
            else:
                file_path = os.path.join(full_dest_path, filename)
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)
            return JSONResponse(
                content={
                    "filename": filename,
                    "destination": full_dest_path,
                    "recursive": recursive,
                },
                status_code=200,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.get("/download_files")
    def download_file(path: str):
        try:
            if not os.path.isabs(path):
                raise HTTPException(
                    status_code=400, detail="Path must be an absolute path"
                )
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="File not found")
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as temp_zip:
                with ZipFile(temp_zip, "w") as zipf:
                    for root, _, files in os.walk(path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            zipf.write(
                                file_path, arcname=os.path.relpath(file_path, path)
                            )
                return FileResponse(
                    path=temp_zip.name,
                    media_type="application/zip",
                    filename=f"{os.path.basename(path)}.zip",
                    background=BackgroundTask(lambda: os.unlink(temp_zip.name)),
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    @app.post("/list_files")
    async def list_files(request: Request):
        client = get_client()
        assert client is not None
        try:
            from backend.runtime.server_utils import (
                _get_sorted_directory_entries,
                _resolve_list_path,
            )

            full_path = await _resolve_list_path(request, client)
            if (
                not full_path
                or not os.path.exists(full_path)
                or not os.path.isdir(full_path)
            ):
                return JSONResponse(content=[])
            sorted_entries = _get_sorted_directory_entries(full_path)
            return JSONResponse(content=sorted_entries)
        except Exception as e:
            logger.error("Error listing files: %s", e)
            return JSONResponse(content=[])
