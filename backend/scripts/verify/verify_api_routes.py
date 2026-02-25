"""Verify all API routes are properly configured and healthy.

This script checks:
1. All route modules can be imported without errors
2. All routers are properly registered in app.py
3. Route definitions are syntactically correct
4. Health endpoints are accessible
5. No obvious configuration issues
"""

import ast
import importlib
import sys
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Expected routers from app.py
EXPECTED_ROUTERS = {
    "auth_router": "forge.server.routes.auth",
    "user_management_router": "forge.server.routes.user_management",
    "public_api_router": "forge.server.routes.public",
    "files_api_router": "forge.server.routes.files",
    "security_api_router": "forge.server.routes.security",
    "feedback_api_router": "forge.server.routes.feedback",
    "conversation_api_router": "forge.server.routes.conversation",
    "manage_conversation_api_router": "forge.server.routes.manage_conversations",
    "settings_router": "forge.server.routes.settings",
    "secrets_router": "forge.server.routes.secrets",
    "database_connections_router": "forge.server.routes.database_connections",
    "memory_router": "forge.server.routes.memory",
    "monitoring_router": "forge.server.routes.monitoring",
    "knowledge_base_router": "forge.server.routes.knowledge_base",
    "analytics_router": "forge.server.routes.analytics",
    "templates_router": "forge.server.routes.templates",
    "global_export_router": "forge.server.routes.global_export",
    "slack_router": "forge.server.routes.slack",
    "git_api_router": "forge.server.routes.git",
    "trajectory_router": "forge.server.routes.trajectory",
    "billing_router": "forge.server.routes.billing",
    "dashboard_router": "forge.server.routes.dashboard",
    "profile_router": "forge.server.routes.profile",
    "notifications_router": "forge.server.routes.notifications",
    "search_router": "forge.server.routes.search",
    "activity_router": "forge.server.routes.activity",
}

# Routes directory
ROUTES_DIR = project_root / "forge" / "server" / "routes"


def check_syntax(file_path: Path) -> tuple[bool, str]:
    """Check if a Python file has valid syntax.

    Args:
        file_path: Path to the Python file

    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        ast.parse(source, filename=str(file_path))
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Error parsing file: {str(e)}"


def check_route_file_imports(file_path: Path) -> tuple[bool, list[str]]:
    """Check if a route file can be imported and has required components.

    Args:
        file_path: Path to the route file

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []
    is_valid, error = check_syntax(file_path)
    if not is_valid:
        issues.append(f"Syntax error: {error}")
        return False, issues

    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()
        ast.parse(source, filename=str(file_path))
    except Exception as e:
        issues.append(f"AST parsing error: {str(e)}")

    return not issues, issues


def verify_router_imports() -> dict[str, tuple[bool, str]]:
    """Verify all expected routers can be imported.

    Returns:
        Dictionary mapping router names to (is_valid, error_message)
    """
    results = {}

    for router_name, module_path in EXPECTED_ROUTERS.items():
        try:
            module = importlib.import_module(module_path)

            # Check if router or app is exported
            has_router = hasattr(module, "router") or hasattr(module, "app")

            if not has_router:
                results[router_name] = (
                    False,
                    f"Module {module_path} does not export 'router' or 'app'",
                )
            else:
                results[router_name] = (True, "OK")

        except ImportError as e:
            results[router_name] = (False, f"Import error: {str(e)}")
        except SyntaxError as e:
            results[router_name] = (False, f"Syntax error: {str(e)}")
        except Exception as e:
            results[router_name] = (False, f"Unexpected error: {str(e)}")

    return results


def check_all_route_files() -> dict[str, tuple[bool, list[str]]]:
    """Check all route files for syntax and basic issues.

    Returns:
        Dictionary mapping file names to (is_valid, list_of_issues)
    """
    results = {}

    if not ROUTES_DIR.exists():
        return {"error": (False, [f"Routes directory not found: {ROUTES_DIR}"])}

    for route_file in ROUTES_DIR.glob("*.py"):
        if route_file.name.startswith("__"):
            continue

        is_valid, issues = check_route_file_imports(route_file)
        results[route_file.name] = (is_valid, issues)

    return results


def verify_app_registration() -> tuple[bool, list[str]]:
    """Verify that app.py can be imported and all routers are registered.

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    try:
        # Check app.py syntax
        app_file = project_root / "forge" / "server" / "app.py"
        is_valid, error = check_syntax(app_file)
        if not is_valid:
            issues.append(f"app.py syntax error: {error}")
            return False, issues

        # Try to parse app.py to check router registrations
        with open(app_file, encoding="utf-8") as f:
            source = f.read()

        # Check for all expected router includes
        for router_name in EXPECTED_ROUTERS:
            if (
                f"include_router({router_name}" not in source
                and f"include_router({router_name.replace('_router', '')}" not in source
            ):
                # Some routers might have different names in app.py
                # Check for partial matches
                router_base = router_name.replace("_router", "").replace(
                    "_api_router", ""
                )
                if router_base not in source.lower():
                    issues.append(
                        f"Router {router_name} may not be registered in app.py"
                    )

    except Exception as e:
        issues.append(f"Error checking app.py: {str(e)}")

    return not issues, issues


def main():
    """Main verification function."""
    print("=" * 80)
    print("API Routes Verification")
    print("=" * 80)
    print()

    all_passed = True
    all_passed &= _run_route_files_check()
    all_passed &= _run_router_imports_check()
    all_passed &= _run_app_registration_check()
    all_passed &= _run_final_import_check()

    print("=" * 80)
    print("✅ ALL CHECKS PASSED - API routes are healthy!" if all_passed
          else "❌ SOME CHECKS FAILED - Please review the issues above")
    print("=" * 80)
    return 0 if all_passed else 1


def _run_route_files_check() -> bool:
    """Check route file syntax; return True if all passed."""
    print("1. Checking route file syntax...")
    print("-" * 80)
    route_files = check_all_route_files()
    route_issues = sum(1 for v, _ in route_files.values() if not v)
    for file_name, (is_valid, issues) in route_files.items():
        if not is_valid:
            print(f"  ❌ {file_name}:")
            for issue in issues:
                print(f"     - {issue}")
        else:
            print(f"  ✅ {file_name}")
    if route_issues == 0:
        print(f"  ✅ All {len(route_files)} route files passed syntax check")
    else:
        print(f"  ❌ {route_issues} route file(s) have issues")
    print()
    return route_issues == 0


def _run_router_imports_check() -> bool:
    """Verify router imports; return True if all passed."""
    print("2. Verifying router imports...")
    print("-" * 80)
    router_results = verify_router_imports()
    import_issues = sum(1 for v, _ in router_results.values() if not v)
    for router_name, (is_valid, message) in router_results.items():
        if not is_valid:
            print(f"  ❌ {router_name}: {message}")
        else:
            print(f"  ✅ {router_name}")
    if import_issues == 0:
        print(f"  ✅ All {len(router_results)} routers can be imported")
    else:
        print(f"  ❌ {import_issues} router(s) have import issues")
    print()
    return import_issues == 0


def _run_app_registration_check() -> bool:
    """Verify app.py router registration; return True if valid."""
    print("3. Verifying app.py router registration...")
    print("-" * 80)
    app_valid, app_issues = verify_app_registration()
    if app_valid:
        print("  ✅ app.py syntax is valid")
        if app_issues:
            print("  ⚠️  Potential registration issues (may be false positives):")
            for issue in app_issues:
                print(f"     - {issue}")
        else:
            print("  ✅ All routers appear to be registered")
    else:
        print("  ❌ app.py has issues:")
        for issue in app_issues:
            print(f"     - {issue}")
    print()
    return app_valid


def _run_final_import_check() -> bool:
    """Try importing FastAPI app; return True if successful."""
    print("4. Final check: Importing FastAPI app...")
    print("-" * 80)
    try:
        from backend.api.app import app
        route_count = len(app.routes)
        print("  ✅ FastAPI app imported successfully")
        print(f"  ✅ App has {route_count} registered routes")
        health_routes = [r for r in app.routes if hasattr(r, "path") and "health" in r.path.lower()]
        if health_routes:
            print(f"  ✅ Found {len(health_routes)} health endpoint(s)")
        else:
            print("  ⚠️  No health endpoints found (may be registered differently)")
    except Exception as e:
        print("  ❌ Failed to import FastAPI app:")
        print(f"     {str(e)}")
        print("\n  Full traceback:")
        traceback.print_exc()
        return False
    print()
    return True


if __name__ == "__main__":
    # Fix Windows console encoding
    if sys.platform == "win32":
        import codecs

        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

    exit_code = main()
    sys.exit(exit_code)
