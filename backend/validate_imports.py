"""Validate all imports before starting the server.

This script attempts to import all modules used by the server to catch
missing dependencies or modules before runtime.
"""

import sys
from pathlib import Path

# When running as a script, python adds the script's dir to sys.path[0].
# This causes issues because 'backend' contains 'mcp', shadowing the 'mcp' library.
# We must remove the script's dir (backend/) from sys.path.
backend_dir = Path(__file__).resolve().parent
sys.path = [p for p in sys.path if Path(p).resolve() != backend_dir]

# Add project root to path (so 'backend' package is importable)
sys.path.insert(0, str(backend_dir.parent))

errors = []
warnings = []


def try_import(module_name: str, description: str = "") -> bool:
    """Try to import a module and report errors."""
    try:
        __import__(module_name)
        return True
    except ImportError as e:
        errors.append(f"[ERROR] {module_name}: {e}")
        if description:
            errors[-1] += f" ({description})"
        return False
    except Exception as e:
        warnings.append(f"[WARNING] {module_name}: {e}")
        if description:
            warnings[-1] += f" ({description})"
        return False


def main():
    """Validate all server imports."""
    print("Validating server imports...\n")

    # Core imports
    print("Checking core modules...")
    try_import("backend.api.app", "Main FastAPI app")
    try_import("backend.api.listen", "Server entry point")

    # Route imports (from app.py)
    print("\nChecking route modules...")
    routes_to_check = [
        ("backend.api.routes.conversation", "Conversation routes"),
        ("backend.api.routes.features", "Features routes"),
        ("backend.api.routes.feedback", "Feedback routes"),
        ("backend.api.routes.files", "File routes"),
        ("backend.api.routes.git", "Git routes"),
        ("backend.api.routes.global_export", "Export routes"),
        ("backend.api.routes.knowledge_base", "Knowledge base routes"),
        ("backend.api.routes.manage_conversations", "Manage conversations routes"),
        ("backend.api.routes.memory", "Memory routes"),
        ("backend.api.routes.monitoring", "Monitoring routes"),
        ("backend.api.routes.public", "Public API routes"),
        ("backend.api.routes.secrets", "Secrets routes"),
        ("backend.api.routes.settings", "Settings routes"),
        ("backend.api.routes.templates", "Templates routes"),
        ("backend.api.routes.trajectory", "Trajectory routes"),
        ("backend.api.routes.profile", "Profile routes"),
        ("backend.api.routes.notifications", "Notifications routes"),
        ("backend.api.routes.search", "Search routes"),
        ("backend.api.routes.mcp", "MCP routes"),
    ]

    for module_name, description in routes_to_check:
        try_import(module_name, description)

    # Print results
    print("\n" + "=" * 70)
    if warnings:
        print(f"\n[WARNING] {len(warnings)} warning(s):")
        for warning in warnings:
            print(f"  {warning}")

    if errors:
        print(f"\n[ERROR] {len(errors)} error(s) found:")
        for error in errors:
            print(f"  {error}")
        print("\n[TIP] Fix these errors before starting the server.")
        return 1

    print("\n[SUCCESS] All imports validated successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
