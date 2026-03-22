"""GUI launcher for Forge CLI."""

import os
import subprocess
import sys
from pathlib import Path

from backend import __version__
from backend.core.app_paths import get_app_settings_root


def ensure_config_dir_exists() -> Path:
    """Ensure the directory for canonical ``settings.json`` exists (app root, not ``~/.Forge``)."""
    root = Path(get_app_settings_root())
    root.mkdir(parents=True, exist_ok=True)
    return root


def launch_gui_server() -> None:
    """Launch the Forge GUI server locally."""
    print(f"🚀 Launching Forge v{__version__} GUI server...")
    print("")

    ensure_config_dir_exists()

    # Check for agent configuration in current directory
    cwd = Path.cwd()
    if (cwd / "agent.yaml").exists():
        print(f"📂 Found agent configuration in {cwd}")
        print("   The agent will be available in the 'Local' workspace.")

    print("")
    print("✅ Starting local Forge server...")
    print("   GUI: http://localhost:3000")
    print("   API: http://localhost:3000/api")
    print("")
    print("Press Ctrl+C to stop the server.")
    print("")

    # Set environment variables for local execution
    env = os.environ.copy()
    env["FORGE_RUNTIME"] = "local"

    try:
        # Check if port 3000 is available (basic check)
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", 3000))
        sock.close()
        if result == 0:
            print("⚠️  Warning: Port 3000 seems to be in use. Server start might fail.")

        # Start the server using uvicorn
        # We use the listen module which mounts the API and Socket.IO
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.api.listen:app",
            "--host",
            "0.0.0.0",
            "--port",
            "3000",
        ]

        subprocess.run(cmd, env=env, check=True)
    except subprocess.CalledProcessError as e:
        print("")
        print("❌ Failed to start Forge GUI server.")
        print(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("")
        print("✓ Forge GUI server stopped successfully.")
        sys.exit(0)
    except Exception as e:
        print("")
        print(f"❌ An unexpected error occurred: {e}")
        sys.exit(1)
