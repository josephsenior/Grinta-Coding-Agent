# Public File API Investigation

The old split between text-oriented and AST-oriented public editors has been
collapsed. The model-facing API is now:

- `read` for file, range, and symbol-body reads.
- `find_symbols` for candidate discovery.
- `create` for new files and new symbols.
- `edit_symbols` for existing symbol modifications or deletion.
- `replace_string` for exact text changes.
- `multiedit` for atomic multi-file refactors.

Implementation details can still reuse lower-level editor primitives internally,
but those primitives are not callable tools and should not appear in prompts.
