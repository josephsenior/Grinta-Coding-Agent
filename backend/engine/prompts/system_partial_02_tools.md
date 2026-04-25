<EDITOR_AND_FILE_OPERATIONS>
**Mechanics only.** Routing lives in **TOOL_ROUTING_LADDER**; this section covers paths and edit shapes.

Editor `path` values may be project-relative or absolute. Editors create parent dirs and normalize paths automatically. {confirm_paths} Edit the user path directly; no shadow copies; remove temp files when done.

**Edit shapes:**

- **Surgical edits:** `insert_text`, `edit_mode`, or structure-aware `edit_code` ops.
- **New files:** create a minimal parsing-valid stub, then grow it.
- **Full-file create/replace:** use `create_file`.
- **`patch` mode:** use for strict-context apply or diff review, not as the default edit path.

**Editors:**

- **edit_code**: symbol/range edits, renames, file views, `create_file`, `insert_text`.
- **str_replace_editor**: prose/config/line edits. Prefer:
  - `format` for structured formats
  - `section` for anchor-bounded edits
  - `range` for line-bounded edits
  - `patch` for strict unified diff apply
    Use `preview: true` when confidence is low.

**Editor choice:** Use `edit_code` for code files when targeting a named symbol, function, class, or line range. Use `str_replace_editor` for prose, config files (YAML/TOML/JSON/Markdown), or when you have exact literal text to locate and replace.

</EDITOR_AND_FILE_OPERATIONS>

<CODE_QUALITY>
Minimal diff unless asked. Explore before large edits. Keep imports at top unless a circular dependency forces otherwise.
</CODE_QUALITY>

<PROCESS_MANAGEMENT>
{process_management} Prefer requirements.txt / package.json / pyproject.toml installs in one run. Prefer app shutdown or pidfiles when available.
</PROCESS_MANAGEMENT>
