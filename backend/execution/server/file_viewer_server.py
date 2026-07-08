"""A tiny, isolated server that provides only the /view endpoint from the action execution server.

This server has no authentication and only listens to localhost traffic.
Paths must fall within configured workspace roots (default: process cwd).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from uvicorn import Config, Server

from backend.core.logging.logger import app_logger as logger
from backend.core.type_safety.path_validation import (
    PathValidationError,
    validate_readable_path,
)
from backend.execution.utils.files.file_viewer import generate_file_viewer_html


def _resolve_workspace_roots(workspace_roots: Sequence[str] | None) -> tuple[str, ...]:
    if workspace_roots:
        return tuple(str(root) for root in workspace_roots if str(root).strip())
    return (os.getcwd(),)


def _validate_view_path(
    path: str,
    workspace_roots: Sequence[str],
    *,
    allow_configured_extra_roots: bool,
) -> Path:
    """Return a resolved path when *path* is readable under the allowed roots."""
    roots = _resolve_workspace_roots(workspace_roots)
    primary = roots[0]
    extra = tuple(Path(root) for root in roots[1:])
    if allow_configured_extra_roots:
        from backend.core.type_safety.path_validation import (
            resolve_configured_extra_read_roots,
        )

        extra = (*extra, *resolve_configured_extra_read_roots())
    return validate_readable_path(
        path,
        primary,
        must_exist=True,
        extra_read_roots=extra or None,
    )


def create_app(
    workspace_roots: Sequence[str] | None = None,
    *,
    allow_configured_extra_roots: bool = True,
) -> FastAPI:
    """Create the FastAPI application.

    Args:
        workspace_roots: Absolute or relative roots whose files may be viewed.
            Defaults to the process working directory when omitted.
        allow_configured_extra_roots: When True, also honor
            ``security.additional_read_roots`` from loaded app config.
    """
    resolved_roots = _resolve_workspace_roots(workspace_roots)
    app = FastAPI(
        title='File Viewer Server', openapi_url=None, docs_url=None, redoc_url=None
    )

    @app.get('/')
    async def root() -> dict[str, str]:
        """Root endpoint to check if the server is running."""
        return {'status': 'File viewer server is running'}

    @app.get('/view')
    async def view_file(path: str, request: Request) -> HTMLResponse:
        """View a file using an embedded viewer.

        Args:
            path (str): The absolute path of the file to view.
            request (Request): The FastAPI request object.

        Returns:
            HTMLResponse: An HTML page with an appropriate viewer for the file.

        """
        client_host = request.client.host if request.client else None
        if client_host not in ['127.0.0.1', 'localhost', '::1']:
            return HTMLResponse(
                content='<h1>Access Denied</h1><p>This endpoint is only accessible from localhost</p>',
                status_code=403,
            )
        if not os.path.isabs(path):
            return HTMLResponse(
                content=f'<h1>Error: Path must be absolute</h1><p>{path}</p>',
                status_code=400,
            )
        try:
            safe_path = _validate_view_path(
                path,
                resolved_roots,
                allow_configured_extra_roots=allow_configured_extra_roots,
            )
        except PathValidationError as exc:
            logger.warning('File viewer rejected path %s: %s', path, exc.message)
            return HTMLResponse(
                content=(
                    '<h1>Access Denied</h1>'
                    f'<p>Path is outside the allowed workspace roots.</p>'
                    f'<p>{exc.message}</p>'
                ),
                status_code=403,
            )
        if safe_path.is_dir():
            return HTMLResponse(
                content=f'<h1>Error: Path is a directory</h1><p>{path}</p>',
                status_code=400,
            )
        try:
            html_content = generate_file_viewer_html(str(safe_path))
            return HTMLResponse(content=html_content)
        except Exception as e:
            return HTMLResponse(
                content=f'<h1>Error viewing file</h1><p>{path}</p><p>{e!s}</p>',
                status_code=500,
            )

    return app


def start_file_viewer_server(
    port: int,
    workspace_roots: Sequence[str] | None = None,
    *,
    allow_configured_extra_roots: bool = True,
) -> tuple[str, threading.Thread]:
    """Start the file viewer server on the specified port or find an available one.

    Args:
        port (int, optional): The port to bind to. If None, an available port will be found.

    Returns:
        Tuple[str, threading.Thread]: The server URL and the thread object.

    """
    server_url = f'http://localhost:{port}'
    port_path = '/tmp/oh-server-url'  # nosec B108 - Safe: runtime communication file
    os.makedirs(os.path.dirname(port_path), exist_ok=True)
    with open(port_path, 'w', encoding='utf-8') as f:
        f.write(server_url)
    logger.info('File viewer server URL saved to /tmp/oh-server-url: %s', server_url)
    logger.info('Starting file viewer server on port %s', port)
    app = create_app(
        workspace_roots=workspace_roots,
        allow_configured_extra_roots=allow_configured_extra_roots,
    )
    config = Config(
        app=app,
        host='127.0.0.1',
        port=port,
        log_level='error',
        ws='websockets-sansio',
    )
    server = Server(config=config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    return (server_url, thread)


if __name__ == '__main__':
    url, thread = start_file_viewer_server(port=8000)
    try:
        thread.join()
    except KeyboardInterrupt:
        logger.info('Server stopped')
