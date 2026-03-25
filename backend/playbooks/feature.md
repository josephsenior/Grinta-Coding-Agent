---
name: feature
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /feature
---

# Structured feature work

Align with system **EXECUTION_DISCIPLINE** and **TASK_MANAGEMENT** (task_tracker for 3+ steps).

## 1. Discover

Read existing code for patterns, similar features, and data flow **before** writing new code. Use **search_code** / targeted reads — avoid repeated directory listings.

## 2. Shape the API

Sketch types/signatures and error cases **before** filling bodies. If the signature feels wrong, fix design first.

## 3. Tests

Add tests that describe acceptance; run them **red** then implement **green**. Prefer the project’s real test stack (`pytest`, `vitest`, etc.).

## 4. Integrate

Check routes, schemas, config, exports, and docs in the **same** change set when the feature touches them.

## 5. Done

Full test run + project lint/typecheck if configured. No secrets in code or logs (system **SECURITY**).
