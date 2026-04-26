<EDITOR_AND_FILE_OPERATIONS>
**Mechanics only.** Routing lives in **TOOL_ROUTING_LADDER**; this section covers paths and edit shapes.

Editor `path` values may be project-relative or absolute. Editors create parent dirs and normalize paths automatically. {confirm_paths} Edit the user path directly; no shadow copies; remove temp files when done.

**Edit shapes:**

- **Surgical edits:** `insert_text`, `edit_mode`, or structure-aware `symbol_editor` ops.
- **New files:** create a minimal parsing-valid stub, then grow it.
- **Full-file create/replace:** use `create_file`.
- **`patch` mode:** use for strict-context apply or diff review, not as the default edit path.

**Editors:**

- **symbol_editor**: symbol/range edits, renames, file views, `create_file`, `insert_text`, `replace_text`.
- **text_editor**: prose/config/line edits. Prefer:
  - `format` for structured formats
  - `section` for anchor-bounded edits
  - `range` for line-bounded edits
  - `patch` for strict unified diff apply
    Use `preview: true` when confidence is low.

**Editor choice:** Use `symbol_editor` when targeting a named symbol, function, class, or line range. Use `text_editor` for prose, config files (YAML/TOML/JSON/Markdown), or when you have exact literal text to locate and replace. Both tools support `replace_text`, `insert_text`, `read_file`, and `create_file`.

</EDITOR_AND_FILE_OPERATIONS>

<CODE_QUALITY>
Minimal diff unless asked. Explore before large edits. Keep imports at top unless a circular dependency forces otherwise.
</CODE_QUALITY>

<PROCESS_MANAGEMENT>
{process_management} Prefer requirements.txt / package.json / pyproject.toml installs in one run. Prefer app shutdown or pidfiles when available.
</PROCESS_MANAGEMENT>
