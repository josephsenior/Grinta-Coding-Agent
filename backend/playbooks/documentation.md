---
name: documentation
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - document
  - add docs
  - generate documentation
  - write documentation
  - docstring
  - update readme
  - update docs
---

# Documentation Best Practices

## Docstrings

### Python — Google style (Forge convention)

```python
def function_name(param: InputType, config: Config) -> OutputType:
    """One-line summary ending with a period.

    Optional longer description for complex functions. Explain
    WHY, not WHAT — the code shows what, the docstring explains intent.

    Args:
        param: What it is and valid values/range.
        config: Controls optional behaviour.

    Returns:
        What the caller gets; mention None if applicable.

    Raises:
        ValueError: When param is invalid.
        RuntimeError: When the underlying operation fails.
    """
```

### TypeScript/JavaScript — JSDoc

```typescript
/**
 * One-line summary.
 *
 * @param input - What it is
 * @param options - Controls behaviour
 * @returns What the caller gets
 * @throws {Error} When something goes wrong
 */
function functionName(input: string, options?: Options): Result {
```

## README Structure

A good README answers these questions in order:

1. **What** — one-sentence description
2. **Why** — the problem it solves (differentiate from alternatives)
3. **Quick start** — working example in under 5 commands
4. **Installation** — prerequisites + exact commands
5. **Usage** — common workflows with examples
6. **Configuration** — key settings and their defaults
7. **Contributing** — how to run tests, code style

```markdown
# Project Name

> One-sentence pitch that differentiates from alternatives.

## Quick Start

\`\`\`bash
pip install project-name
project-name init
project-name run "do something"
\`\`\`

## Installation
...
```

## What to Document vs. What to Skip

**Document:**
- Public API and non-obvious parameters
- Why a non-obvious decision was made (`# Using X instead of Y because Z`)
- Module/class level overview: what it is, what it is NOT
- Configuration options and their defaults

**Skip:**
- What the code obviously does (`i += 1  # increment i`)
- Redundant type restatement (`param (str): a string`)
- Auto-generated files

## Keeping Docs Fresh

- Docs rot. Update them in the same PR as the code change.
- If you can't explain it in a docstring, the interface may need simplifying.
- Mark stale sections with `TODO(docs): update for X change` rather than leaving wrong information.

## API Documentation

For REST APIs, update `openapi.json` whenever routes or schemas change:

```bash
# Regenerate after schema changes
uv run python -m backend.api --export-openapi > openapi.json
```
