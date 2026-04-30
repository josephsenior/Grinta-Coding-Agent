import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / '.github' / 'workflows'
LABELS_FILE = REPO_ROOT / '.github' / 'labels.yml'

LABEL_EXPR_RE = re.compile(r"github\.event\.label\.name\s*==\s*'([^']+)'")
REQUIRED_ARRAY_RE = re.compile(r'required=\(\s*(.*?)\s*\)', re.DOTALL)
QUOTED_PATH_RE = re.compile(r'"([^"]+)"')
SKIP_DYNAMIC_PATHS = {'/tmp/requirements.txt'}
AUTOMATIC_TRIGGER_KEYS = (
    'push',
    'pull_request',
    'schedule',
    'issues',
    'issue_comment',
    'pull_request_review',
    'pull_request_review_comment',
)


def load_defined_labels() -> set[str]:
    labels: set[str] = set()
    current_name: str | None = None
    for raw_line in LABELS_FILE.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if line.startswith('- name:'):
            value = line.split(':', 1)[1].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            current_name = value
            labels.add(current_name)
        elif current_name and line.startswith('name:'):
            value = line.split(':', 1)[1].strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            labels.add(value)
    return labels


def check_workflow_labels(defined_labels: set[str]) -> list[str]:
    errors: list[str] = []
    for workflow_file in sorted(WORKFLOWS_DIR.glob('*.yml')):
        text = workflow_file.read_text(encoding='utf-8')
        for label in LABEL_EXPR_RE.findall(text):
            if label not in defined_labels:
                rel = workflow_file.relative_to(REPO_ROOT)
                errors.append(
                    f'{rel}: label "{label}" is referenced but not defined in .github/labels.yml'
                )
    return errors


def has_automatic_triggers(workflow_text: str) -> bool:
    on_block_match = re.search(r'(?ms)^on:\n(.*?)(^\S|\Z)', workflow_text)
    if not on_block_match:
        return False

    on_block = on_block_match.group(1)
    for key in AUTOMATIC_TRIGGER_KEYS:
        if re.search(rf'(?m)^\s+{re.escape(key)}\s*:', on_block):
            return True
    return False


def check_required_paths_exist() -> list[str]:
    errors: list[str] = []
    for workflow_file in sorted(WORKFLOWS_DIR.glob('*.yml')):
        text = workflow_file.read_text(encoding='utf-8')
        if not has_automatic_triggers(text):
            # Manual-only workflows are intentionally allowed to reference absent assets.
            continue
        for block in REQUIRED_ARRAY_RE.findall(text):
            for path in QUOTED_PATH_RE.findall(block):
                if path in SKIP_DYNAMIC_PATHS:
                    continue
                if not (REPO_ROOT / path).exists():
                    rel = workflow_file.relative_to(REPO_ROOT)
                    errors.append(
                        f'{rel}: required path "{path}" does not exist in repository'
                    )
    return errors


def main() -> int:
    if not LABELS_FILE.exists():
        print('Missing .github/labels.yml', file=sys.stderr)
        return 1

    defined_labels = load_defined_labels()
    errors = [
        *check_workflow_labels(defined_labels),
        *check_required_paths_exist(),
    ]

    if errors:
        print('Workflow config consistency check failed:', file=sys.stderr)
        for err in errors:
            print(f' - {err}', file=sys.stderr)
        return 1

    print('Workflow config consistency check passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
