"""Apply-patch tool — atomic multi-file edits via unified diff.

Applies a unified diff (``git diff`` / ``diff -u`` format) to the workspace
using ``git apply``, which handles multi-file operations atomically.  The
patch content is base64-encoded before embedding in the shell command to
eliminate all shell-quoting and injection risks.

If the workspace is not a git repository, the tool transparently falls back
to the POSIX ``patch`` command.

Why this is valuable
--------------------
Without this tool the LLM must perform N sequential editor calls to modify N
files in a coordinated change (e.g. rename a symbol across the codebase).
Each step generates new context and a separate verification round.
``apply_patch`` collapses all of that into a single atomic operation.
"""

from __future__ import annotations

import base64
import re

from backend.core.constants import APPLY_PATCH_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.engine.tools.prompt import build_python_exec_command
from backend.ledger.action import CmdRunAction

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    '**CRITICAL: Exact Format Required**\n'
    'You MUST verify the exact target file contents and line numbers using `read_file` or `grep_search` before using this tool.\n'
    'This tool applies a unified diff (`git diff` / `diff -u` format) to the workspace atomically.\n\n'
    '**CORRECT USAGE EXAMPLE:**\n'
    '```diff\n'
    'diff --git a/path/to/file.py b/path/to/file.py\n'
    '--- a/path/to/file.py\n'
    '+++ b/path/to/file.py\n'
    '@@ -12,4 +12,4 @@\n'
    ' def my_function():\n'
    '-    return False\n'
    '+    return True\n'
    '```\n\n'
    '**STRICT REQUIREMENTS:**\n'
    '- Must start with `diff --git a/<file> b/<file>`\n'
    '- Followed by `--- a/<file>` (or `/dev/null` for new files)\n'
    '- Followed by `+++ b/<file>` (or `/dev/null` for deleted files)\n'
    '- Followed by hunk headers `@@ -n,m +n,m @@`\n'
    '- Context lines (unchanged) must start with a single space.\n'
    '- Added lines must start with `+`.\n'
    '- Removed lines must start with `-`.\n'
    '- You MUST explicitly set the `i_have_verified_file_contents_and_format` argument to `true`.\n'
)

def create_apply_patch_tool() -> ChatCompletionToolParam:
    """Create the apply-patch tool definition."""
    return create_tool_definition(
        name=APPLY_PATCH_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            'patch': {
                'type': 'string',
                'description': (
                    'Complete git unified diff to apply (multi-file supported). '
                    'Must include diff --git, ---/+++, and @@ hunk headers. '
                    'Index line is optional, but if present it must be valid.'
                ),
            },
            'i_have_verified_file_contents_and_format': {
                'type': 'boolean',
                'description': (
                    'You MUST explicitly set this to `true` to acknowledge that you have '
                    'recently verify the exact file contents using `read_file` or `grep_search` '
                    'and reviewed the correct patch format requirements.'
                ),
            },
            'check_only': {
                'type': 'string',
                'enum': ['true', 'false'],
                'description': (
                    "If 'true', validate the patch would apply cleanly without actually "
                    "modifying any files (dry-run). Defaults to 'false'."
                ),
            },
        },
        required=['patch', 'i_have_verified_file_contents_and_format'],
    )


# ---------------------------------------------------------------------------
# Action builder
# ---------------------------------------------------------------------------

_DIFF_HEADER_RE = re.compile(r'^diff --git a/.+ b/.+$')
_HUNK_HEADER_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')


def validate_apply_patch_contract(patch: str) -> str | None:
    """Return a human-readable validation error when patch headers are malformed."""
    lines = [line for line in patch.splitlines() if not line.startswith('index ')]
    if not lines:
        return 'Patch is empty.'

    starts = [i for i, line in enumerate(lines) if line.startswith('diff --git ')]
    if not starts:
        return 'Missing `diff --git a/<file> b/<file>` header.'

    starts.append(len(lines))
    for block_index in range(len(starts) - 1):
        start = starts[block_index]
        end = starts[block_index + 1]
        block = lines[start:end]
        if not block:
            continue

        if not _DIFF_HEADER_RE.match(block[0]):
            return f'Line {start + 1}: malformed diff header.'

        minus_rel = next((i for i, line in enumerate(block[1:], start=1) if line.startswith('--- ')), None)
        plus_rel = next((i for i, line in enumerate(block[1:], start=1) if line.startswith('+++ ')), None)
        if minus_rel is None or plus_rel is None:
            return f'Line {start + 1}: missing `---`/`+++` file header lines.'
        if plus_rel <= minus_rel:
            return f'Line {start + 1}: header order must be diff --git, ---, +++, @@.'

        minus_line = block[minus_rel]
        plus_line = block[plus_rel]
        if not (minus_line.startswith('--- a/') or minus_line == '--- /dev/null'):
            return (
                f'Line {start + minus_rel + 1}: malformed `---` header; '
                'expected `--- a/<file>` or `--- /dev/null`.'
            )
        if not (plus_line.startswith('+++ b/') or plus_line == '+++ /dev/null'):
            return (
                f'Line {start + plus_rel + 1}: malformed `+++` header; '
                'expected `+++ b/<file>` or `+++ /dev/null`.'
            )

        hunk_rel = next((i for i, line in enumerate(block[1:], start=1) if line.startswith('@@ ')), None)
        if hunk_rel is None:
            return f'Line {start + 1}: missing `@@ -n,m +n,m @@` hunk header.'
        if hunk_rel <= plus_rel:
            return f'Line {start + 1}: hunk header must appear after `+++`.'
        if not _HUNK_HEADER_RE.match(block[hunk_rel]):
            return (
                f'Line {start + hunk_rel + 1}: malformed hunk header. '
                'Expected `@@ -n,m +n,m @@`.'
            )

    return None


def _guidance_message(validation_error: str) -> str:
    return (
        '[APPLY_PATCH_GUIDANCE] ' + validation_error + ' '
        'This tool requires a full unified diff in this order: '
        'diff --git, optional valid index, ---, +++, @@. '
        'Regenerate the patch via `git diff` and retry.'
    )


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def build_apply_patch_action(patch: str, check_only: bool = False, i_have_verified_file_contents_and_format: bool = False) -> CmdRunAction:
    """Return a CmdRunAction that applies the unified diff to the workspace."""
    patch = '\n'.join(line for line in patch.splitlines() if not line.startswith('index '))
    validation_error = validate_apply_patch_contract(patch)
    if validation_error is not None:
        py = f"""
import sys

print({_guidance_message(validation_error)!r})
sys.exit(2)
"""
        label = 'dry-run check' if check_only else 'applying patch'
        return CmdRunAction(
            command=build_python_exec_command(py),
            thought=f'[APPLY PATCH] {label}',
            display_label='Validating patch' if check_only else 'Applying patch',
        )

    pb = _b64(patch)
    dry_run_arg = 'True' if check_only else 'False'

    py = f"""
import base64, os, pathlib, subprocess, sys, tempfile

try:
    import whatthepatch  # type: ignore
except Exception:
    whatthepatch = None

patch = base64.b64decode(b'{pb}').decode()

added = 0
removed = 0
for raw_line in patch.splitlines():
    if raw_line.startswith('diff --git '):
        continue
    if raw_line.startswith('index '):
        continue
    if raw_line.startswith('+++ '):
        continue
    if raw_line.startswith('--- '):
        continue
    if raw_line.startswith('@@ '):
        continue
    if raw_line.startswith('Binary files '):
        continue
    if raw_line.startswith('\\ No newline at end of file'):
        continue
    if raw_line.startswith('+'):
        added += 1
    elif raw_line.startswith('-'):
        removed += 1


def _run_git_apply(temp_name, dry_run):
    git_args = ['git', 'apply', '--whitespace=fix']
    if dry_run:
        git_args.append('--check')
    git_args.append(temp_name)
    try:
        return subprocess.run(git_args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return None


def _run_patch_apply(temp_name, dry_run):
    patch_args = ['patch', '-p1']
    if dry_run:
        patch_args.insert(1, '--dry-run')
    patch_args += ['--input', temp_name]
    try:
        return subprocess.run(patch_args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return None


def _apply_python_fallback(patch_text, dry_run):
    if whatthepatch is None:
        return 1, (
            '[APPLY_PATCH_GUIDANCE] Neither `git` nor `patch` command is available, '
            'and Python fallback dependency `whatthepatch` is missing.'
        )

    try:
        diffs = list(whatthepatch.parse_patch(patch_text))
    except Exception as exc:
        return 1, 'Failed to parse unified diff in python fallback: ' + str(exc)

    if not diffs:
        return 1, 'No patch hunks were parsed by python fallback.'

    touched = 0
    for diff in diffs:
        header = getattr(diff, 'header', None)
        if header is None:
            return 1, 'Patch header missing in python fallback parser.'

        old_path = getattr(header, 'old_path', None)
        new_path = getattr(header, 'new_path', None)

        is_new = old_path == '/dev/null'
        is_delete = new_path == '/dev/null'
        target_path = old_path if is_delete else new_path
        if not target_path:
            return 1, 'Could not determine target path from patch header.'

        path_obj = pathlib.Path(target_path)
        if path_obj.is_absolute() or '..' in path_obj.parts:
            return 1, 'Unsafe target path in patch header: ' + target_path

        if (not is_new) and (not path_obj.exists()):
            return 1, 'Target file not found for patch: ' + target_path

        original_text = ''
        if path_obj.exists():
            original_text = path_obj.read_text(
                encoding='utf-8',
                errors='surrogateescape',
            )
        original_lines = original_text.splitlines(keepends=True)
        line_ending = '\\r\\n' if '\\r\\n' in original_text else '\\n'

        out_lines = []
        cursor = 0
        for change in diff.changes:
            old_no = getattr(change, 'old', None)
            new_no = getattr(change, 'new', None)
            line_text = (getattr(change, 'line', '') or '')

            if old_no is not None:
                old_idx = max(0, int(old_no) - 1)
                if old_idx > len(original_lines):
                    return 1, 'Patch line reference out of range in ' + target_path

                if old_idx < cursor:
                    old_idx = cursor

                out_lines.extend(original_lines[cursor:old_idx])

                if old_idx < len(original_lines):
                    source_line = original_lines[old_idx].rstrip('\\r\\n')
                    if source_line != line_text.rstrip('\\r\\n'):
                        return (
                            1,
                            'Patch context mismatch in '
                            + target_path
                            + ' at line '
                            + str(old_no),
                        )

                cursor = min(len(original_lines), old_idx + 1)
                if new_no is not None:
                    out_lines.append(line_text + line_ending)
            else:
                if new_no is not None:
                    out_lines.append(line_text + line_ending)

        out_lines.extend(original_lines[cursor:])

        if dry_run:
            touched += 1
            continue

        if is_delete:
            if path_obj.exists():
                path_obj.unlink()
            touched += 1
            continue

        path_obj.parent.mkdir(parents=True, exist_ok=True)
        path_obj.write_text(''.join(out_lines), encoding='utf-8', errors='surrogateescape')
        touched += 1

    if dry_run:
        return 0, 'Dry run OK via python fallback (' + str(touched) + ' files)'
    return 0, 'Patch applied via python fallback (' + str(touched) + ' files)'

with tempfile.NamedTemporaryFile(suffix='.patch', delete=False, mode='w') as f:
    f.write(patch)
    temp_name = f.name

dry_run = {dry_run_arg}

git_result = _run_git_apply(temp_name, dry_run)
r = git_result

git_not_repo = (
    git_result is not None
    and git_result.returncode != 0
    and 'not a git repository' in (git_result.stderr or '').lower()
)

if git_result is None or git_not_repo:
    patch_result = _run_patch_apply(temp_name, dry_run)
    if patch_result is not None and patch_result.returncode == 0:
        r = patch_result
    else:
        code, fallback_msg = _apply_python_fallback(patch, dry_run)
        os.unlink(temp_name)
        if code != 0:
            if patch_result is not None:
                prior = ((patch_result.stdout or '') + '\\n' + (patch_result.stderr or '')).strip()
                if prior:
                    print((prior + '\\n' + fallback_msg).strip())
                    sys.exit(patch_result.returncode)
            print(fallback_msg)
            sys.exit(code)

        out = fallback_msg
        stats = f'[APPLY_PATCH_STATS] +{{added}} -{{removed}}'
        out = (out + '\\n' + stats).strip() if out else stats
        print(out)
        sys.exit(0)

combined = ((r.stdout or '') + '\\n' + (r.stderr or '')).strip()
if r.returncode != 0 and 'corrupt patch' in combined.lower():
    guidance = (
        '[APPLY_PATCH_GUIDANCE] The patch appears malformed or in the wrong format. '
        'This tool expects a standard unified diff (git diff / diff -u), not a custom patch DSL. '
        'Regenerate the patch in unified diff format and retry.'
    )
    print((combined + '\\n\\n' + guidance).strip())
    os.unlink(temp_name)
    sys.exit(r.returncode)

os.unlink(temp_name)

out = r.stdout or r.stderr or ('Dry run OK, patch applies cleanly.' if dry_run else 'Patch applied successfully.')
if r.returncode == 0:
    stats = f'[APPLY_PATCH_STATS] +{{added}} -{{removed}}'
    out = (out + '\\n' + stats).strip() if out else stats
print(out)
sys.exit(r.returncode)
"""

    label = 'dry-run check' if check_only else 'applying patch'
    return CmdRunAction(
        command=build_python_exec_command(py),
        thought=f'[APPLY PATCH] {label}',
        display_label='Validating patch' if check_only else 'Applying patch',
    )
