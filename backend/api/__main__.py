"""Command-line entrypoint for launching the Forge server with Uvicorn."""

import os
import warnings

import uvicorn


def main() -> None:
    """Start the Forge server with optimized configuration.

    This function initializes and runs the uvicorn server with performance
    optimizations for development and production environments.

    Environment Variables:
        port: Server port (default: 3000)
        WORKERS: Number of worker processes (default: 1 for dev, use gunicorn for production)
        DEBUG: Enable debug logging (default: false)
        HOST: Server host (default: 0.0.0.0)

    Production Deployment:
        For production with multiple workers, use gunicorn:
        gunicorn backend.api.listen:app \
            --workers 4 \
            --worker-class uvicorn.workers.UvicornWorker \
            --bind 0.0.0.0:3000 \
            --timeout 300
    """
    warnings.filterwarnings("ignore", category=SyntaxWarning, module="pydub\\.utils")
    try:
        port = int(os.environ.get("port") or os.environ.get("PORT") or "3000")
    except ValueError:
        port = 3000
    host = os.environ.get("HOST") or "0.0.0.0"
    try:
        workers = int(os.environ.get("WORKERS") or "1")
    except ValueError:
        workers = 1

    # Suppress Uvicorn's default startup message and show custom one
    import sys

    # Warn if trying to use multiple workers with uvicorn.run (not recommended)
    if workers > 1:
        sys.stderr.write(
            "\n\033[33mWARNING\033[0m: Multiple workers with uvicorn.run() is not recommended.\n"
            "For production, use gunicorn with uvicorn workers instead.\n"
            "Falling back to single worker mode.\n\n"
        )
        sys.stderr.flush()
        workers = 1

    # Print custom startup message before uvicorn starts
    sys.stderr.write(
        f"\n\033[32mINFO\033[0m:     Uvicorn running on http://{host}:{port} (Press CTRL+C to quit)\n"
    )
    sys.stderr.flush()

    # Configure logging to suppress uvicorn's startup message
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": True,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default"],
                "level": "WARNING",
            },  # Suppress INFO startup message
            "uvicorn.error": {"level": "WARNING"},
        },
    }
    uvicorn.run(
        "backend.api.listen:app",
        host=host,  # nosec B104 - Safe: web server intentionally accessible on all interfaces
        port=port,
        log_config=log_config,
        log_level="debug" if os.environ.get("DEBUG") else "info",
        # Performance optimizations
        workers=workers,  # Single worker for development, use gunicorn for production
        loop="asyncio",
        http="httptools",  # Faster HTTP parser
        access_log=False,  # Disable access logs in production
    )


if __name__ == "__main__":
    main()
