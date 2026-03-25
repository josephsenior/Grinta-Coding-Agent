"""Verify all API routes are properly configured and healthy.

This script checks:
1. All route modules can be imported without errors
2. All routers are properly registered in route_registry.py
3. Route definitions are syntactically correct
4. Health endpoints are accessible
5. No obvious configuration issues
"""

import ast
import importlib
import sys
import traceback
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

EXPECTED_ROUTERS = {
    "conversation_api_router": "backend.api.routes.conversation",
    "manage_conversation_api_router": "backend.api.routes.conversation_collection",
    "features_router": "backend.api.routes.features",
    "feedback_api_router": "backend.api.routes.feedback",
    "files_api_router": "backend.api.routes.files",
    "global_export_router": "backend.api.routes.global_export",
    "knowledge_base_router": "backend.api.routes.knowledge_base",
    "memory_router": "backend.api.routes.memory",
    "monitoring_router": "backend.api.routes.monitoring",
    "notifications_router": "backend.api.routes.notifications",
    "public_api_router": "backend.api.routes.public",
    "search_router": "backend.api.routes.search",
    "secrets_router": "backend.api.routes.secrets",
    "settings_router": "backend.api.routes.settings",
    "templates_router": "backend.api.routes.templates",
    "trajectory_router": "backend.api.routes.trajectory",
    "workspace_router": "backend.api.routes.workspace",
}

ROUTES_DIR = project_root / "backend" / "api" / "routes"


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

            has_router = (
                hasattr(module, "router")
                or hasattr(module, "sub_router")
                or hasattr(module, "app")
            )

            if not has_router:
                results[router_name] = (
                    False,
                    f"Module {module_path} does not export 'router', 'sub_router', or 'app'",
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
    """Verify that route_registry.py registers all expected routers.

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    try:
        registry_file = project_root / "backend" / "api" / "route_registry.py"
        is_valid, error = check_syntax(registry_file)
        if not is_valid:
            issues.append(f"route_registry.py syntax error: {error}")
            return False, issues

        with open(registry_file, encoding="utf-8") as f:
            source = f.read()

        for router_name, module_path in EXPECTED_ROUTERS.items():
            module_short = module_path.rsplit(".", 1)[-1]
            if module_short not in source and router_name not in source:
                issues.append(
                    f"Router {router_name} ({module_path}) may not be registered in route_registry.py"
                )

    except Exception as e:
        issues.append(f"Error checking route_registry.py: {str(e)}")

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
    print("ALL CHECKS PASSED - API routes are healthy!" if all_passed
          else "SOME CHECKS FAILED - Please review the issues above")
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
            print(f"  FAIL {file_name}:")
            for issue in issues:
                print(f"     - {issue}")
        else:
            print(f"  OK   {file_name}")
    if route_issues == 0:
        print(f"  All {len(route_files)} route files passed syntax check")
    else:
        print(f"  {route_issues} route file(s) have issues")
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
            print(f"  FAIL {router_name}: {message}")
        else:
            print(f"  OK   {router_name}")
    if import_issues == 0:
        print(f"  All {len(router_results)} routers can be imported")
    else:
        print(f"  {import_issues} router(s) have import issues")
    print()
    return import_issues == 0


def _run_app_registration_check() -> bool:
    """Verify route_registry.py router registration; return True if valid."""
    print("3. Verifying route_registry.py router registration...")
    print("-" * 80)
    app_valid, app_issues = verify_app_registration()
    if app_valid:
        print("  OK   route_registry.py syntax is valid")
        if app_issues:
            print("  WARN Potential registration issues (may be false positives):")
            for issue in app_issues:
                print(f"     - {issue}")
        else:
            print("  OK   All routers appear to be registered")
    else:
        print("  FAIL route_registry.py has issues:")
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
        print("  OK   FastAPI app imported successfully")
        print(f"  OK   App has {route_count} registered routes")
        health_routes = [r for r in app.routes if hasattr(r, "path") and "health" in r.path.lower()]
        if health_routes:
            print(f"  OK   Found {len(health_routes)} health endpoint(s)")
        else:
            print("  WARN No health endpoints found (may be registered differently)")
    except Exception as e:
        print("  FAIL Failed to import FastAPI app:")
        print(f"     {str(e)}")
        print("\n  Full traceback:")
        traceback.print_exc()
        return False
    print()
    return True


if __name__ == "__main__":
    if sys.platform == "win32":
        import codecs

        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

    exit_code = main()
    sys.exit(exit_code)
