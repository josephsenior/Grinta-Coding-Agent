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

from backend.core.constants import APPLY_PATCH_TOOL_NAME
from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.ledger.action import CmdRunAction

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "Apply a unified diff patch to the workspace in one atomic operation.\n\n"
    "When to use:\n"
    "- Renaming a symbol across multiple files\n"
    "- Applying a pre-computed diff from `git diff` or `diff -u`\n"
    "- Making coordinated changes across several files simultaneously\n\n"
    "The `patch` parameter should be a valid unified diff string "
    "(the output of `git diff` or `diff -u old new`).\n\n"
    "After applying, the tool shows which files were modified. "
    "Use `str_replace_editor command='view_file'` to confirm the result."
)


def create_apply_patch_tool() -> ChatCompletionToolParam:
    """Create the apply-patch tool definition."""
    return create_tool_definition(
        name=APPLY_PATCH_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            "patch": {
                "type": "string",
                "description": (
                    "The unified diff patch to apply. Must be valid unified diff format "
                    "(as produced by `git diff` or `diff -u`). "
                    "Multi-file patches are fully supported."
                ),
            },
            "check_only": {
                "type": "string",
                "enum": ["true", "false"],
                "description": (
                    "If 'true', validate the patch would apply cleanly without actually "
                    "modifying any files (dry-run). Defaults to 'false'."
                ),
            },
        },
        required=["patch"],
    )


# ---------------------------------------------------------------------------
# Action builder
# ---------------------------------------------------------------------------

def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def build_apply_patch_action(patch: str, check_only: bool = False) -> CmdRunAction:
    """Return a CmdRunAction that applies the unified diff to the workspace."""
    pb = _b64(patch)
    dry_run_arg = "True" if check_only else "False"

    py = (
        "import base64,os,subprocess,sys,tempfile;"
        f"patch=base64.b64decode(b'{pb}').decode();"
        "f=tempfile.NamedTemporaryFile(suffix='.patch',delete=False,mode='w');"
        "f.write(patch);f.close();"
        f"dry_run={dry_run_arg};"
        # Try git apply first
        "git_args=['git','apply','--whitespace=fix'];"
        "dry_run and git_args.append('--check');"
        "git_args.append(f.name);"
        "r=subprocess.run(git_args,capture_output=True,text=True);"
        # Fall back to patch if not a git repo
        "if r.returncode!=0 and 'not a git repository' in r.stderr.lower():"
        "  patch_args=['patch','-p1'];"
        "  dry_run and patch_args.insert(1,'--dry-run');"
        "  patch_args+=['--input',f.name];"
        "  r=subprocess.run(patch_args,capture_output=True,text=True);"
        "os.unlink(f.name);"
        "out=r.stdout or r.stderr or ('Dry run OK, patch applies cleanly.' if dry_run else 'Patch applied successfully.');"
        "print(out);"
        "sys.exit(r.returncode)"
    )

    label = "dry-run check" if check_only else "applying patch"
    return CmdRunAction(
        command=f'python -c "{py}"',
        thought=f"[APPLY PATCH] {label}",
    )
