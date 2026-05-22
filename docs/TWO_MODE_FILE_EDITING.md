# Two-Mode File Editing Protocol

Normal Grinta tools remain native JSON/provider tool calls. File content never
travels through JSON arguments.

`start_file_edit` captures metadata only: path, operation, line ranges, symbol
targets, batch edit descriptors, hash guards, and other validation inputs. When
content is required, the runtime opens FILE EDITOR MODE and disables tools. The
model must then output one strict heredoc-style `<file_edit>` block using the
runtime-generated delimiter.

Single-target edits such as `replace_range` and `edit_symbol` place one raw
content payload directly inside `<file_edit>`.

Batch edits still use raw content rather than JSON:
- `edit_symbols` uses repeated `<symbol name="..."> ... </symbol>` blocks
- `multi_edit` uses repeated `<edit index="N"> ... </edit>` blocks

Each inner block has its own runtime-generated delimiter, and the runtime binds
those raw bodies back to the metadata from the original `start_file_edit` call.

The runtime extracts raw content from that block and converts it into the
existing internal file editor action. Existing path safety, hash checks, syntax
checks, diffs, checkpoint/rollback middleware, and post-edit validation still
run on that internal action.

This avoids JSON escaping failures for code payloads without turning the whole
agent into XML. Editor mode is isolated so normal tool use and raw file-content
capture do not share a protocol.
