# File Editing Surface

Grinta exposes a single native tool-call surface for file and code work:

- `read` inspects files, ranges, or one or more symbol bodies.
- `find_symbols` discovers symbol candidates without reading full bodies.
- `create` creates new files.
- `replace_string` performs exact one-file text replacement, insertion by anchor, and deletion.
- `multiedit` stages coordinated `replace_string` changes across one or more files and commits them atomically.
- `undo_last_edit` reverts the last content edit on an existing file.

The model should choose intent, not transport format. Raw editor modes and
file-edit blocks are not part of the public protocol. The runtime remains
responsible for path safety, content guardrails, syntax checks, diffs,
checkpoint/rollback behavior, and atomic writes.
