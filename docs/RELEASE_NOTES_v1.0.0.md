# Grinta 1.0 — First Stable Release

> **Draft only. Do not publish until every GA gate and the required green window pass.**

Grinta 1.0 is the first stable release of a local-first, provider-agnostic coding agent designed to complete long, failure-prone software tasks.

## Highlights

- Local execution, session state, checkpoints, and audit trails
- Provider-agnostic inference across hosted and local models
- LSP and debugger integrations
- Recovery-oriented orchestration for failures, timeouts, malformed tool calls, and context pressure
- Chat, Plan, and Agent workflows in a terminal UI
- Risk classification, confirmation gates, secret masking, and execution profiles

## Evidence

The launch evidence includes the sanitized 4h 33m autonomous-run report with 16,393 events and 373 tool outcomes, plus the Raft recovery recording distributed as a GitHub Release asset.

## Install

```bash
pipx install grinta
grinta
```

Python 3.12 and 3.13 are supported. Consult the support matrix and security checklist before increasing autonomy or running against untrusted repositories.

## Release integrity

The release must be built from the signed `v1.0.0` tag, smoke-tested as exact wheel and sdist artifacts on Linux and Windows, and published through PyPI Trusted Publishing. Checksums and attestations accompany the release artifacts.
