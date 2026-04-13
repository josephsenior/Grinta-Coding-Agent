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
    'Apply a unified diff patch to the workspace in one atomic operation.\n\n'
    'When to use:\n'
    '- Renaming a symbol across multiple files\n'
    '- Applying a pre-computed diff from `git diff` or `diff -u`\n'
    '- Making coordinated changes across several files simultaneously\n\n'
    'CRITICAL: `patch` must be a complete git unified diff with full headers.\n'
    'Required lines, in order:\n'
    '1. diff --git a/<file> b/<file>\n'
    '2. index <old_hash>..<new_hash> <mode>\n'
    '3. --- a/<file>\n'
    '4. +++ b/<file>\n'
    '5. @@ -n,m +n,m @@\n\n'
    'Common errors:\n'
    '- "corrupt patch at line X" usually means the index line is missing.\n'
    '- "patch does not apply" usually means headers or hunk context are incomplete.\n\n'
    'Always generate patches via `git diff` when possible.\n\n'
    'After applying, the tool shows which files were modified. '
    "Use `str_replace_editor command='view_file'` to confirm the result."
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
                    'Must include diff --git, index, ---/+++, and @@ hunk headers.'
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
        required=['patch'],
    )


# ---------------------------------------------------------------------------
# Action builder
# ---------------------------------------------------------------------------

_DIFF_HEADER_RE = re.compile(r'^diff --git a/.+ b/.+$')
_INDEX_RE = re.compile(r'^index [0-9a-fA-F]{7,64}\.\.[0-9a-fA-F]{7,64} [0-7]{6}$')
_HUNK_HEADER_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@')


def validate_apply_patch_contract(patch: str) -> str | None:
    """Return a human-readable validation error when patch headers are malformed."""
    lines = patch.splitlines()
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

        index_rel = next((i for i, line in enumerate(block[1:], start=1) if line.startswith('index ')), None)
        if index_rel is None:
            return (
                f'Line {start + 1}: missing `index <old_hash>..<new_hash> <mode>` line '
                'after the diff header.'
            )
        if not _INDEX_RE.match(block[index_rel]):
            return (
                f'Line {start + index_rel + 1}: malformed index line. '
                'Expected `index <old_hash>..<new_hash> <mode>`.'
            )

        minus_rel = next((i for i, line in enumerate(block[1:], start=1) if line.startswith('--- ')), None)
        plus_rel = next((i for i, line in enumerate(block[1:], start=1) if line.startswith('+++ ')), None)
        if minus_rel is None or plus_rel is None:
            return f'Line {start + 1}: missing `---`/`+++` file header lines.'
        if minus_rel <= index_rel or plus_rel <= minus_rel:
            return f'Line {start + 1}: header order must be diff --git, index, ---, +++, @@.'

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
        'This tool requires a full git unified diff in this exact order: '
        'diff --git, index <old_hash>..<new_hash> <mode>, ---, +++, @@. '
        'Do not auto-correct or strip headers; regenerate the patch via `git diff` and retry.'
    )


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def build_apply_patch_action(patch: str, check_only: bool = False) -> CmdRunAction:
    """Return a CmdRunAction that applies the unified diff to the workspace."""
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
import base64, os, subprocess, sys, tempfile

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

with tempfile.NamedTemporaryFile(suffix='.patch', delete=False, mode='w') as f:
    f.write(patch)
    temp_name = f.name

dry_run = {dry_run_arg}

git_args = ['git', 'apply', '--whitespace=fix']
if dry_run:
    git_args.append('--check')
git_args.append(temp_name)

r = subprocess.run(git_args, capture_output=True, text=True)

if r.returncode != 0 and 'not a git repository' in r.stderr.lower():
    patch_args = ['patch', '-p1']
    if dry_run:
        patch_args.insert(1, '--dry-run')
    patch_args += ['--input', temp_name]
    r = subprocess.run(patch_args, capture_output=True, text=True)

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
