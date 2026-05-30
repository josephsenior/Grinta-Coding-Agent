# 36. The Facade Pattern and the Smaller File API

There is a moment in systems engineering where you realize the complexity is no
longer in the code itself, but in the interface you are forcing the user to
navigate.

For Grinta, the user is the model.

The current editing facade keeps the backend responsible for path safety, AST
location, validation, diffs, and atomic commits, while the model sees only a
small intent-oriented API:

- `read`
- `find_symbols`
- `create`
- `edit_symbols`
- `replace_string`
- `multiedit`

The rule is now simple: read may search, write must target. The model does not
choose a transport format or editor mode. It chooses whether it needs context,
a new file or symbol, a symbol edit, an exact string replacement, or an atomic
multi-file refactor.

The backend keeps its structural machinery. The prompt keeps one clear mental
model.

---

← [The Semantic Memory That Survived](39-the-semantic-memory-that-survived.md) | [The Book of Grinta](README.md) | [The Road Ahead](07-the-road-ahead.md) →
