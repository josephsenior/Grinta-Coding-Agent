# 36. The Facade Pattern and the Escape from JSON Prison

There is a moment in systems engineering where you realize the complexity is no longer in the code itself, but in the interface you are forcing the user to navigate.

For Grinta, the user is the model.

By the time I reached this phase of the architecture, the backend was hardened. The event ledger worked. The circuit breakers held. The 1,327-line Tree-sitter engine could perfectly slice and mutate the AST of 45 different languages.

But the agent was still failing high-stakes refactors.

It wasn't failing because it couldn't reason. It was failing because I was making it pay a massive, invisible cognitive tax every time it tried to speak to the filesystem. I had built a powerful engine, but the steering wheel was covered in thorns.

This chapter is about the final architectural pivot of the editing loop: separating the complexity of the backend from the cognitive load of the prompt, and finally killing the JSON escaping prison for good.

---

## The Cognitive Reality Check

When you spend months writing complex capabilities, you want to expose all of them.

I had built two separate tools: `text_editor` for line-based surgical edits, and `symbol_editor` for AST-aware structural edits. Between them, they exposed over 17 distinct commands and 40 different parameters.

To insert new code, the model had to remember that `text_editor` expected a parameter called `new_str`, while `symbol_editor` expected `new_code` or sometimes `new_body`. For simple operations like reading a file, it had to arbitrarily guess which tool to invoke.

I was asking a probabilistic next-token predictor to juggle two competing mental models, memorize arbitrary parameter naming drift, and perfectly execute complex routing logic in a single turn.

A critical review of the execution logs laid out the brutal truth: having two tools doing the same thing creates choice paralysis. The agent was hallucinating parameters not because it was stupid, but because the interface was designed to induce hallucination.

---

## The Facade Architecture

The temptation was to tear down the backend and merge the Python execution files. But that would mean mixing heavy Tree-sitter AST logic with basic string-replacement logic, destroying the architectural boundaries I fought so hard to build in [03. The Architectural Gauntlet](03-the-architectural-gauntlet.md).

The breakthrough was realizing that what the model sees does not have to be what the runtime executes.

I built a Facade Pattern.

I deleted `text_editor` and `symbol_editor` from the system prompt entirely. In their place, I exposed a single, unified tool: `<function=file_editor>`.

I standardized the entire vocabulary. Whether the model is replacing a line range, rewriting a class body, or applying a patch, the payload parameter is always exactly one word: `content`.

```xml
<function=file_editor>
<parameter=command>edit_symbol</parameter>
<parameter=symbol_name>UserAuth</parameter>
<parameter=content>
class UserAuth:
    # No more parameter hallucination
    pass
</parameter>
</function>
```

Underneath, the `file_editor.py` execution handler acts as a zero-friction router, silently mapping that unified `content` payload back to `new_str`, `new_body`, or `patch_text` depending on the command, before routing it to the appropriate underlying engine.

The model gets a zero-cognitive-load interface. The backend keeps its 1,327-line structural integrity.

---

## The Final Boss: The multi_edit Array

Even with the Facade in place, there was one stealth hazard left.

For cross-file refactoring, I had built a `multi_edit` command. But because I was still anchored to standard data structures, I defined the payload as a JSON array of objects: `[{"path": "...", "content": "..."}]`.

This was a trap.

By forcing the model to wrap multiple file edits inside a JSON array, I was shoving it right back into the JSON escaping prison. If the model generated code with a double quote or a literal newline inside that array, it had to mentally calculate the `\"` and `\n` escaping rules across hundreds of lines of code. If it missed a single backslash in file #3, the JSON parser imploded, the atomic transaction rolled back, and the session burned to the ground.

The fix was pure, JSON-free nested XML:

```xml
<function=file_editor>
<parameter=command>multi_edit</parameter>
<file_edit>
  <path>src/auth.py</path>
  <operation>edit_symbol</operation>
  <content>
def login():
    print("Raw, unescaped text forever.")
  </content>
</file_edit>
</function>
```

---

## The Single Universal Law

By moving `multi_edit` to nested XML tags, Grinta finally achieved a single, unbreakable physical law for the model: **Code payloads are always raw, unescaped text.** It doesn't matter if it's one file or five files. The transport physics never change.

I started this project thinking that reliability came from adding more loops, more validators, and more agents. I ended it by realizing that true reliability comes from designing an interface so naturally aligned with the model's physics that it is almost impossible for it to make a syntax error.

---

← [The Semantic Memory That Survived](39-the-semantic-memory-that-survived.md) | [The Book of Grinta](README.md) | [The Road Ahead](07-the-road-ahead.md) →
