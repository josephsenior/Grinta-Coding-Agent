import os
import re
import sys


def find_version_references(directory: str) -> tuple[set[str], set[str]]:
    FORGE_versions = set()
    runtime_versions = set()
    version_pattern_forge = re.compile('Forge:(\\d{1})\\.(\\d{2})')
    version_pattern_runtime = re.compile('runtime:(\\d{1})\\.(\\d{2})')
    for root, _, files in os.walk(directory):
        if '.git' in root or 'docs/build' in root:
            continue
        for file in files:
            if file.endswith(
                ('.md', '.yml', '.yaml', '.txt', '.html', '.py', '.js', '.ts')
            ):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, encoding='utf-8') as f:
                        content = f.read()
                        if matches := version_pattern_forge.findall(content):
                            print(f'Found Forge version {matches} in {file_path}')
                            FORGE_versions.update(matches)
                        if matches := version_pattern_runtime.findall(content):
                            print(f'Found runtime version {matches} in {file_path}')
                            runtime_versions.update(matches)
                except Exception as e:
                    print(f'Error reading {file_path}: {e}', file=sys.stderr)
    return (FORGE_versions, runtime_versions)


def main():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    print(f'Checking version consistency in {repo_root}')
    FORGE_versions, runtime_versions = find_version_references(repo_root)
    print(f'Found Forge versions: {sorted(FORGE_versions)}')
    print(f'Found runtime versions: {sorted(runtime_versions)}')
    exit_code = 0
    if len(FORGE_versions) > 1:
        print('Error: Multiple Forge versions found:', file=sys.stderr)
        print('Found versions:', sorted(FORGE_versions), file=sys.stderr)
        exit_code = 1
    elif len(FORGE_versions) == 0:
        print('Warning: No Forge version references found', file=sys.stderr)
    if len(runtime_versions) > 1:
        print('Error: Multiple runtime versions found:', file=sys.stderr)
        print('Found versions:', sorted(runtime_versions), file=sys.stderr)
        exit_code = 1
    elif len(runtime_versions) == 0:
        print('Warning: No runtime version references found', file=sys.stderr)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
