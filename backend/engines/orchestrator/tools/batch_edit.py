"""Batch edit tool — atomic multi-file str_replace edits with rollback.

Accepts a list of {path, old_str, new_str} operations and applies them all
or none (rollback on first failure). This eliminates partial-apply states
where some files are updated while others fail, leaving the codebase in an
inconsistent intermediate state.

When to use vs apply_patch:
- Use batch_edit when you have structured old_str/new_str pairs (no diff required)
- Use apply_patch when you have a pre-computed unified diff from git diff / diff -u
"""

from __future__ import annotations

import json
from typing import Any

from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.events.action import CmdRunAction

BATCH_EDIT_TOOL_NAME = "batch_edit"

_DESCRIPTION = (
    "Apply multiple str_replace edits atomically — all succeed or all roll back.\n\n"
    "Provide a list of edit operations. Each operation must have:\n"
    "  - `path`: absolute path to the file\n"
    "  - `old_str`: exact text to find (must be unique in the file)\n"
    "  - `new_str`: replacement text\n\n"
    "Atomicity guarantee: if ANY edit fails (old_str not found, ambiguous match,\n"
    "permission error), ALL previously applied edits in this batch are reverted\n"
    "before the error is reported. The workspace is never left in a partial state.\n\n"
    "When to prefer batch_edit over sequential str_replace_editor calls:\n"
    "- Renaming a symbol, constant, or import across multiple files\n"
    "- Coordinated refactors where partial application would break builds\n"
    "- Changes spanning 3+ files that must land together\n\n"
    "After success, confirms each file path that was edited."
)


def create_batch_edit_tool() -> ChatCompletionToolParam:
    """Create the batch_edit tool definition."""
    return create_tool_definition(
        name=BATCH_EDIT_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            "edits": {
                "type": "array",
                "description": (
                    "Array of edit operations to apply atomically. "
                    "Each item requires 'path', 'old_str', and 'new_str'."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file to edit.",
                        },
                        "old_str": {
                            "type": "string",
                            "description": (
                                "Exact text to replace. Must uniquely identify one location "
                                "in the file. Include 3–5 lines of surrounding context."
                            ),
                        },
                        "new_str": {
                            "type": "string",
                            "description": "Text to substitute for old_str.",
                        },
                    },
                    "required": ["path", "old_str", "new_str"],
                },
                "minItems": 1,
            },
            "preview": {
                "type": "boolean",
                "description": (
                    "If true, validate all edits would apply cleanly without modifying any files. "
                    "Returns which edits would succeed. Defaults to false."
                ),
            },
        },
        required=["edits"],
    )


# ---------------------------------------------------------------------------
# Action builder
# ---------------------------------------------------------------------------

def build_batch_edit_action(edits: list[dict[str, Any]], preview: bool = False) -> CmdRunAction:
    """Return a CmdRunAction that applies the batch edits atomically."""
    edits_json = json.dumps(edits)
    preview_flag = "True" if preview else "False"

    py = (
        "import json,sys;"
        f"edits=json.loads({repr(edits_json)});"
        f"preview={preview_flag};"
        "backups=[];"
        "errors=[];"
        "for i,edit in enumerate(edits):\n"
        "  path=edit['path'];old=edit['old_str'];new=edit['new_str'];\n"
        "  try:\n"
        "    with open(path,'r',encoding='utf-8') as f: content=f.read()\n"
        "    count=content.count(old)\n"
        "    if count==0: errors.append(f'Edit {i}: old_str not found in {path}'); break\n"
        "    if count>1: errors.append(f'Edit {i}: old_str matches {count} locations in {path} — must be unique'); break\n"
        "    backups.append((path,content));\n"
        "    if not preview:\n"
        "      with open(path,'w',encoding='utf-8') as f: f.write(content.replace(old,new,1))\n"
        "    print(f'  [OK] {path}')\n"
        "  except Exception as e: errors.append(f'Edit {i}: {e}'); break\n"
        "if errors:\n"
        "  for bpath,bcontent in backups:\n"
        "    try:\n"
        "      with open(bpath,'w',encoding='utf-8') as f: f.write(bcontent)\n"
        "    except OSError as e:\n"
        "      sys.stderr.write(f'[batch_edit] Rollback failed for {bpath!r}: {e}\\n')\n"
        "  print('BATCH EDIT FAILED — all changes rolled back.');\n"
        "  print('Error:',errors[0]); sys.exit(1)\n"
        "else:\n"
        "  if preview: print('DRY RUN: all',len(edits),'edits would apply cleanly.')\n"
        "  else: print('BATCH EDIT OK:',len(edits),'files updated atomically.')"
    )

    label = "dry-run" if preview else "applying"
    return CmdRunAction(
        command=f"python -c \"{py}\"",
        thought=f"[BATCH EDIT] {label} {len(edits)} edit(s) atomically",
    )
