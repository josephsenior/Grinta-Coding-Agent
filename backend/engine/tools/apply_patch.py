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
    "**CRITICAL: Exact Format Required**\n"
    "You MUST verify target file contents using `read_file` or `grep_search` IMMEDIATELY before using this tool.\n"
    "This tool applies a unified diff (`git diff` / `diff -u` format) atomically.\n\n"
    "**CORRECT USAGE EXAMPLE:**\n"
    "```diff\n"
    "diff --git a/path/to/file.py b/path/to/file.py\n"
    "--- a/path/to/file.py\n"
    "+++ b/path/to/file.py\n"
    "@@ -12,4 +12,4 @@\n"
    " def my_function():\n"
    "-    return False\n"
    "+    return True\n"
    "```\n\n"
    "**STRICT REQUIREMENTS:**\n"
    "- Must start with `diff --git a/<file> b/<file>`\n"
    "- Followed by `--- a/<file>` and `+++ b/<file>` lines.\n"
    "- Followed by hunk headers `@@ -n,m +n,m @@`.\n"
    "- **MANDATORY CONTEXT SPACES**: Unchanged lines MUST start with a single space.\n"
    "- Change lines must start with `+` or `-`.\n\n"
    "**COMMON FAILURES TO AVOID (CRITICAL):**\n"
    "- **NO MARKDOWN**: Do not include '```diff' blocks INSIDE the patch string.\n"
    "- **NO ELLIPSES**: Never use '...' to skip lines. Hunks must be contiguous.\n"
    "- **NO MISSING SPACES**: Omission of the leading space on context lines will cause 'corrupt patch' errors.\n"
    "- **EOF HANDLING**: If a file does not end in a newline, include `\\ No newline at end of file`.\n"
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
                    'Complete git unified diff. Must include diff --git, ---/+++, and @@ hunk headers. '
                    'Ensure context lines start with a single space.'
                ),
            },
            'last_verified_line_content': {
                'type': 'string',
                'description': (
                    'The exact content of the FIRST line of context in your patch, exactly as seen in your last `read_file` call. '
                    'This forces you to verify the file content before patching.'
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
        required=['patch', 'last_verified_line_content'],
    )


# ---------------------------------------------------------------------------
# Action builder
# ---------------------------------------------------------------------------

_DIFF_HEADER_RE = re.compile(r'^diff --git a/.+ b/.+$')
_FILE_MINUS_RE = re.compile(r'^--- (a/.+|/dev/null)$')
_FILE_PLUS_RE = re.compile(r'^\+\+\+ (b/.+|/dev/null)$')
_HUNK_HEADER_RE = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@')


def _classify_patch_error(validation_error: str) -> str:
    message = validation_error.lower()
    if 'context verification' in message or 'latest file content' in message:
        return 'stale_view'
    if 'target file not found' in message:
        return 'tool_unavailable'
    if 'context mismatch' in message:
        return 'context_mismatch'
    return 'malformed_patch'


def _is_contract_error(validation_result: str) -> bool:
    return validation_result.startswith(('Patch', 'Missing', 'Malformed', 'Unexpected'))


def _parse_hunk_header_full(header_line: str) -> tuple[int, int, int, int] | None:
    match = _HUNK_HEADER_RE.match(header_line)
    if not match:
        return None
    old_start = int(match.group(1))
    old_count = int(match.group(2) or '1')
    new_start = int(match.group(3))
    new_count = int(match.group(4) or '1')
    return (old_start, old_count, new_start, new_count)


def validate_apply_patch_contract(patch: str) -> str:
    """Validate unified-diff structure and return normalized patch or error text."""
    lines = [line for line in patch.splitlines() if not line.startswith('index ')]
    if not lines:
        return 'Patch is empty.'

    if any(line.strip().startswith('```') for line in lines):
        return 'Malformed patch: remove markdown fences and pass raw unified diff only.'

    has_git = any(line.startswith('diff --git ') for line in lines)
    has_hunk = any(line.startswith('@@ ') for line in lines)
    if not has_git or not has_hunk:
        is_just_plus_minus = all(
            line.startswith(('+', '-', ' ')) or not line.strip() for line in lines
        )
        if is_just_plus_minus and (
            any(line.startswith('+') for line in lines)
            or any(line.startswith('-') for line in lines)
        ):
            return "Missing unified diff headers. You provided +/- lines but forgot 'diff --git', '---', '+++', and '@@' hunk headers."
        return 'Missing required diff headers (diff --git, ---/+++, or @@).'

    diff_starts = [
        idx for idx, line in enumerate(lines) if line.startswith('diff --git ')
    ]
    for block_idx, block_start in enumerate(diff_starts):
        if not _DIFF_HEADER_RE.match(lines[block_start]):
            return 'Malformed diff header: expected `diff --git a/<path> b/<path>`.'

        block_end = (
            diff_starts[block_idx + 1]
            if block_idx + 1 < len(diff_starts)
            else len(lines)
        )
        block = lines[block_start:block_end]

        minus_line = next((line for line in block if line.startswith('--- ')), None)
        plus_line = next((line for line in block if line.startswith('+++ ')), None)
        if minus_line is None or plus_line is None:
            return 'Malformed patch: each diff block must contain both --- and +++ headers.'
        if not _FILE_MINUS_RE.match(minus_line):
            return 'Malformed `---` header: expected `--- a/<path>` or `--- /dev/null`.'
        if not _FILE_PLUS_RE.match(plus_line):
            return 'Malformed `+++` header: expected `+++ b/<path>` or `+++ /dev/null`.'

        hunk_indices = [
            block_start + idx
            for idx, line in enumerate(block)
            if line.startswith('@@ ')
        ]
        if not hunk_indices:
            return 'Malformed patch: each diff block must include at least one @@ hunk header.'

        for hunk_pos, hunk_start in enumerate(hunk_indices):
            parsed_counts = _parse_hunk_header_full(lines[hunk_start])
            if parsed_counts is None:
                return 'Malformed hunk header: expected `@@ -n,m +n,m @@`.'

            old_start, old_expected, new_start, new_expected = parsed_counts
            hunk_end = (
                hunk_indices[hunk_pos + 1]
                if hunk_pos + 1 < len(hunk_indices)
                else block_end
            )

            old_seen = 0
            new_seen = 0
            for line in lines[hunk_start + 1 : hunk_end]:
                if not line:
                    continue
                if line.startswith('\\ No newline at end of file'):
                    continue
                if line.startswith(' '):
                    old_seen += 1
                    new_seen += 1
                    continue
                if line.startswith('-'):
                    old_seen += 1
                    continue
                if line.startswith('+'):
                    new_seen += 1
                    continue
                return (
                    "Unexpected line in hunk body: all hunk lines must start with "
                    "space, '+', '-', or '\\ No newline at end of file'."
                )

            if old_seen != old_expected or new_seen != new_expected:
                # Auto-correct the hunk header
                lines[hunk_start] = f'@@ -{old_start},{old_seen} +{new_start},{new_seen} @@'

    return '\n'.join(lines)


def _guidance_message(validation_error: str) -> str:
    error_class = _classify_patch_error(validation_error)
    return (
        f'[APPLY_PATCH_CLASS:{error_class}] '
        '[APPLY_PATCH_GUIDANCE] ' + validation_error + ' '
        'This tool requires a full unified diff in this order: '
        'diff --git, optional valid index, ---, +++, @@. '
        'Regenerate the patch via `git diff` and retry.'
    )


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def build_apply_patch_action(
    patch: str,
    check_only: bool = False,
    last_verified_line_content: str = '',
) -> CmdRunAction:
    """Return a CmdRunAction that applies the unified diff to the workspace."""
    result = validate_apply_patch_contract(patch)
    if _is_contract_error(result):
        validation_error = result
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

    if not last_verified_line_content:
        py = """
import sys

print("[APPLY_PATCH_FAILURE] Missing mandatory context verification. "
      "You must provide 'last_verified_line_content' to prove you read the file "
      "immediately before patching.")
sys.exit(2)
"""
        return CmdRunAction(
            command=build_python_exec_command(py),
            thought='[APPLY PATCH] missing verification',
            display_label='Aborting patch',
        )

    # If validation passed, result contains the normalized patch
    patch = result
    patch = '\n'.join(
        line for line in patch.splitlines() if not line.startswith('index ')
    )
    # Auto-heal common LLM issue: missing terminal newline can break patch parsers.
    if patch and not patch.endswith('\n'):
        patch += '\n'

    pb = _b64(patch)
    dry_run_arg = 'True' if check_only else 'False'

    py = f"""
import base64, os, pathlib, subprocess, sys, tempfile

try:
    import whatthepatch  # type: ignore
except Exception:
    whatthepatch = None

patch = base64.b64decode(b'{pb}').decode()
# Force LF uniformly in the patch string so git apply acts predictably
# and cross-platform issues are bypassed.
patch = patch.replace('\\r\\n', '\\n')

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
    if raw_line.startswith('\\\\ No newline at end of file'):
        continue
    if raw_line.startswith('+'):
        added += 1
    elif raw_line.startswith('-'):
        removed += 1


def _run_git_apply(temp_name, dry_run):
    git_args = ['git', 'apply', '--whitespace=fix', '--recount', '--inaccurate-eof', '--verbose']
    if dry_run:
        git_args.append('--check')
    git_args.append(temp_name)
    try:
        return subprocess.run(git_args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return None


def _run_patch_apply(temp_name, dry_run):
    patch_args = ['patch', '-p1', '--batch']
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
                            f'[APPLY_PATCH_GUIDANCE] Patch context mismatch in {{target_path}} at line {{old_no}}. '
                            f'Expected: "{{line_text.rstrip()}}", Found: "{{source_line.rstrip()}}". '
                            f'Ensure you have the latest file content.'
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

with tempfile.NamedTemporaryFile(suffix='.patch', delete=False, mode='w', newline='\\n', encoding='utf-8') as f:
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
if r.returncode != 0:
    guidance = (
        '[APPLY_PATCH_GUIDANCE] The patch failed to apply. '
        'Verify the file contents and line numbers match exactly. '
        'If you used "git diff", ensure you updated your local view with "read_file" first. '
        'The tool expects a standard unified diff (git diff / diff -u).'
    )
    if 'corrupt patch' in combined.lower() or 'malformed' in combined.lower():
        guidance = (
            '[APPLY_PATCH_GUIDANCE] The patch appears malformed or in the wrong format. '
            'This tool expects a standard unified diff (git diff / diff -u), not a custom patch DSL. '
            'Regenerate the patch in unified diff format and retry.'
        )
    # Report the exact error and guidance
    print(f"Error applying patch (code {{r.returncode}}):\\n{{combined}}\\n\\n{{guidance}}")
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
