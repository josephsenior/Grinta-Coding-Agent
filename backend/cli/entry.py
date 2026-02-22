"""Main entry point for Forge CLI with subcommand support."""

import sys
import os
import subprocess
import time
import signal
from pathlib import Path

from backend.core.config import get_cli_parser
from backend.cli.gui_launcher import launch_gui_server


def _handle_help_request(parser) -> None:
    """Handle help request and display comprehensive help information."""
    parser.print_help()
    sys.exit(0)


def _normalize_arguments() -> None:
    """Normalize command line arguments."""
    if len(sys.argv) == 1 or (
        len(sys.argv) > 1 and sys.argv[1] not in ["serve", "all", "start", "init"]
    ):
        sys.argv.insert(1, "serve")


def _handle_version_request(args) -> None:
    """Handle version request and exit."""
    if hasattr(args, "version") and args.version:
        sys.exit(0)


def _launch_all_in_one() -> None:
    """Launch both backend server and TUI in the same terminal session."""
    import httpx
    from tui.app import ForgeApp
    from tui.client import ForgeClient

    # 0. Check for Redis (Mandatory dependency)
    try:
        import redis

        r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=1)
        r.ping()
        print("[OK] Redis connection verified.")
    except Exception as e:
        print("[WARNING] Redis connection failed. Some features may be limited.")
        print("   If you are running locally, please ensure redis-server is running.")
        print(f"   Error: {e}")

    # 1. Start backend server in background
    env = os.environ.copy()
    env["FORGE_RUNTIME"] = "local"

    server_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.api.listen:app",
        "--host",
        "127.0.0.1",
        "--port",
        "3001",
        "--log-level",
        "warning",  # Keep logs quiet so they don't corrupt TUI
    ]

    # Redirection to a log file instead of a pipe avoids uvicorn blocking
    # when the stdout pipe buffer fills up, which is common during startup.
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    server_log = open(log_dir / "server.log", "w", encoding="utf-8")

    server_proc = subprocess.Popen(
        server_cmd, env=env, stdout=server_log, stderr=subprocess.STDOUT, text=True
    )

    def cleanup(sig=None, frame=None):
        print("\nCleanup: Stopping server...")
        server_proc.terminate()
        server_proc.wait()
        server_log.close()
        sys.exit(0)

    # Register cleanup handlers
    try:
        signal.signal(signal.SIGINT, cleanup)
        signal.signal(signal.SIGTERM, cleanup)
    except (ValueError, RuntimeError):
        # On Windows or non-main threads, some signals may not be available
        pass

    # 2. Wait for server to be ready
    print("[*] Waiting for backend to initialize...")
    max_retries = 30
    ready = False
    for i in range(max_retries):
        if server_proc.poll() is not None:
            print("[ERROR] Backend process exited prematurely.")
            server_log.close()
            with open(log_dir / "server.log", "r", encoding="utf-8") as f:
                print("\nBackend output:")
                print("-" * 40)
                print(f.read())
                print("-" * 40)
            sys.exit(1)

        try:
            with httpx.Client() as client:
                response = client.get("http://localhost:3001/api/health/ready")
                if response.status_code == 200:
                    ready = True
                    break
        except Exception:
            pass
        time.sleep(0.5)
        if i % 5 == 0 and i > 0:
            print(f"   Still waiting ({i / 2}s elapsed)...")

    if not ready:
        print("[ERROR] Backend failed to start. Aborting.")
        server_proc.terminate()
        sys.exit(1)

    # 3. Launch TUI in foreground
    print("[OK] Backend ready! Launching TUI...")
    try:
        client = ForgeClient(base_url="http://localhost:3001")
        app = ForgeApp(client)
        app.run()
    finally:
        cleanup()


def _execute_command(args, parser) -> None:
    """Execute the appropriate command based on parsed arguments."""
    if args.command == "serve":
        launch_gui_server()
    elif args.command in ("all", "start"):
        _launch_all_in_one()
    elif args.command == "health":
        # Import dynamically to avoid loading heavy modules if not requested
        from backend.cli.cli.health_check import run_health_check

        run_health_check(args)
    elif args.command == "init":
        from backend.cli.cli.init_project import init_project

        init_project(args.project_name, args.template)
    else:
        parser.print_help()
        sys.exit(1)


def main() -> None:
    """Launch the CLI entry point with subcommand support."""
    parser = get_cli_parser()

    if len(sys.argv) == 2 and sys.argv[1] in ("--help", "-h"):
        _handle_help_request(parser)

    _normalize_arguments()
    args = parser.parse_args()

    _handle_version_request(args)
    _execute_command(args, parser)


if __name__ == "__main__":
    main()
