"""Quick script to verify new endpoints are registered with versioning tags."""

import codecs
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# New endpoints that were added
NEW_ENDPOINTS = [
    "dashboard",
    "profile",
    "notifications",
    "search",
    "activity",
]


def main():
    app_py = project_root / "forge" / "server" / "app.py"
    content = app_py.read_text(encoding="utf-8")

    print("Verifying new endpoints are registered with versioning...\n")

    all_found = True
    for endpoint in NEW_ENDPOINTS:
        # Check if router is imported
        import_pattern = f"from backend.gateway.routes.{endpoint} import"
        include_pattern = f"app.include_router({endpoint}_router"
        tags_pattern = f'tags=["v1", "{endpoint}"]'

        has_import = import_pattern in content
        has_include = include_pattern in content
        has_tags = (
            tags_pattern in content
            or f'tags=["v1", "{endpoint.replace("_", "-")}"]' in content
        )

        if has_import and has_include and has_tags:
            print(f"[OK] {endpoint}: Properly registered with v1 tags")
        else:
            print(f"[FAIL] {endpoint}: Missing registration")
            if not has_import:
                print(f"   - Missing import: {import_pattern}")
            if not has_include:
                print(f"   - Missing include_router: {include_pattern}")
            if not has_tags:
                print("   - Missing v1 tags")
            all_found = False

    if all_found:
        print("\n[SUCCESS] All new endpoints are properly registered with versioning!")
        return 0
    print("\n[ERROR] Some endpoints need to be registered")
    return 1


if __name__ == "__main__":
    sys.exit(main())
