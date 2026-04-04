"""Script to verify API versioning support across all endpoints.

Checks if all API routes support versioning by:
1. Checking if routes use versioned prefixes (/api/v1/...)
2. Verifying route versioning behavior is in place
3. Listing all endpoints that need versioning
"""

import codecs
import re
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Color codes for terminal output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
RESET = '\033[0m'


def check_route_file(file_path: Path) -> dict:
    """Check a route file for versioning support."""
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        return {'error': str(e), 'file': str(file_path)}

    # Check for APIRouter prefix patterns
    prefix_patterns = [
        r'APIRouter\(prefix=["\'](/api/[^"\']+)["\']',
        r'prefix=["\'](/api/[^"\']+)["\']',
    ]

    prefixes = []
    for pattern in prefix_patterns:
        matches = re.findall(pattern, content)
        prefixes.extend(matches)

    # Check if using create_versioned_router
    uses_versioned_router = 'create_versioned_router' in content

    # Check if prefix includes /v1/
    has_versioned_prefix = any('/v1/' in prefix for prefix in prefixes)
    has_non_versioned_prefix = any(
        prefix.startswith('/api/') and '/v1/' not in prefix for prefix in prefixes
    )

    return {
        'file': str(file_path),
        'prefixes': prefixes,
        'uses_versioned_router': uses_versioned_router,
        'has_versioned_prefix': has_versioned_prefix,
        'has_non_versioned_prefix': has_non_versioned_prefix,
    }


def _process_route_results(
    route_files: list[Path], results: list[dict]
) -> tuple[int, int, list[dict]]:
    """Process results and print per-file status. Returns (versioned, non_versioned, needs_update)."""
    versioned_count = 0
    non_versioned_count = 0
    needs_update: list[dict] = []

    for route_file, result in zip(route_files, results, strict=True):
        if 'error' in result:
            print(f'{RED}❌ {route_file.name}: {result["error"]}{RESET}')
            continue

        if result['uses_versioned_router']:
            print(f'{GREEN}✅ {route_file.name}: Uses create_versioned_router{RESET}')
            versioned_count += 1
        elif result['has_versioned_prefix']:
            print(f'{GREEN}✅ {route_file.name}: Has /api/v1/ prefix{RESET}')
            versioned_count += 1
        elif result['has_non_versioned_prefix']:
            print(
                f'{YELLOW}⚠️  {route_file.name}: Uses non-versioned /api/ prefix{RESET}'
            )
            if result['prefixes']:
                for prefix in result['prefixes']:
                    print(f'   └─ Prefix: {prefix}')
            non_versioned_count += 1
            needs_update.append(result)
        else:
            print(f'{YELLOW}⚠️  {route_file.name}: No clear prefix found{RESET}')
            if result['prefixes']:
                for prefix in result['prefixes']:
                    print(f'   └─ Prefix: {prefix}')

    return versioned_count, non_versioned_count, needs_update


def _print_summary(
    versioned_count: int, non_versioned_count: int, route_count: int
) -> None:
    """Print verification summary."""
    print(f'\n{BLUE}{"=" * 60}{RESET}')
    print(f'{BLUE}Summary{RESET}')
    print(f'{BLUE}{"=" * 60}{RESET}')
    print(f'{GREEN}✅ Versioned routes: {versioned_count}{RESET}')
    print(f'{YELLOW}⚠️  Non-versioned routes: {non_versioned_count}{RESET}')
    print(f'{BLUE}📁 Total route files: {route_count}{RESET}')


def _print_needs_update(needs_update: list[dict]) -> None:
    """Print routes that need versioning and recommendation."""
    print(f'\n{YELLOW}⚠️  Routes that need versioning update:{RESET}')
    for result in needs_update:
        print(f'  - {Path(result["file"]).name}')
        if result['prefixes']:
            for prefix in result['prefixes']:
                suggested = prefix.replace('/api/', '/api/v1/', 1)
                print(f'    {prefix} → {suggested}')
    print(f'\n{YELLOW}Recommendation:{RESET}')
    print('  Update routes to use create_versioned_router() or /api/v1/ prefix')
    print('  Add explicit redirects during beta')


def main():
    """Main verification function."""
    print(f'{BLUE}Verifying API Versioning Support{RESET}\n')

    routes_dir = project_root / 'app' / 'server' / 'routes'
    if not routes_dir.exists():
        print(f'{RED}❌ Routes directory not found: {routes_dir}{RESET}')
        return 1

    route_files = [f for f in routes_dir.glob('*.py') if f.name != '__init__.py']
    print(f'Found {len(route_files)} route files\n')

    results = [check_route_file(f) for f in sorted(route_files)]
    versioned_count, non_versioned_count, needs_update = _process_route_results(
        sorted(route_files), results
    )

    _print_summary(versioned_count, non_versioned_count, len(route_files))

    if needs_update:
        _print_needs_update(needs_update)
        return 1
    print(f'\n{GREEN}✅ All routes support versioning!{RESET}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
