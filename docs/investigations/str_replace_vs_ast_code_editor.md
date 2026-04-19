# `str_replace_editor` vs `ast_code_editor` (updated)

## `str_replace_editor` (LLM)

Commands: **`view_file`**, **`create_file`**, **`insert_text`**, **`undo_last_edit`**, plus **`edit_mode`** (`format` \| `section` \| `range` \| `patch`).

There is **no** `replace_text`, `view_and_replace`, or **`batch_replace`** tool surface — multi-file work is **sequential** tool calls (and checkpoints when you need rollback).

## `ast_code_editor`

Structure-aware edits (`replace_range`, symbol commands, …) plus delegated **`view_file`**, **`create_file`**, **`insert_text`**, **`undo_last_edit`** (same routing as `str_replace_editor` for those).

## Internal opcode

`FileEditAction` may still use an internal `replace_text` opcode in the execution layer for legacy paths; it is not a callable tool command.
