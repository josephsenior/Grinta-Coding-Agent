---
name: documentation
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /docs
---

# Documentation

Use when the user invokes **`/docs`**.

## Python docstrings (Google style)

One-line summary; then **Args**, **Returns**, **Raises** as needed. Explain **why** for non-obvious behaviour; skip redundant restatement of types the signature already shows.

## README outline

1. What / why  
2. Quick start (copy-paste commands)  
3. Install / prerequisites  
4. Usage & configuration  
5. Contributing & tests  

## What to skip

Obvious line-by-line narration, redundant `(str): a string`, generated files.

## Freshness

Update docs in the **same** change as code. If temporarily wrong, `TODO(docs): …` beats silent drift.

## OpenAPI (when this repo exposes HTTP APIs)

Regenerate or hand-update **`openapi.json`** when routes/schemas change — follow existing project scripts.
