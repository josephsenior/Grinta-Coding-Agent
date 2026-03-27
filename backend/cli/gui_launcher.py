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
    """Launch the canonical local Forge server entrypoint."""
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
    print("   Delegating to start_server.py (canonical local server entrypoint)")
    print("")

    env = os.environ.copy()
    env["FORGE_RUNTIME"] = "local"
    start_server_path = Path(__file__).resolve().parents[2] / "start_server.py"

    try:
        cmd = [sys.executable, str(start_server_path)]
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

