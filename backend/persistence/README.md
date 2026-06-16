# Grinta persistence

Grinta is **local-first**. Session durability, event streams, audit logs, and
workspace checkpoints are stored on disk under `~/.grinta/workspaces/<id>/storage`
for installed runs (or the configured app root).

## What ships today

| Backend | Status | Use |
| --- | --- | --- |
| **Local filesystem** (`local`) | Default | Production CLI workflow |
| **In-memory** (`memory`) | Supported | Tests and ephemeral runs |

Remote object-store adapters (S3, GCS) and webhook-forwarding file stores were
removed to keep the single-user CLI path predictable.

## Configuration

User-facing settings live in `settings.json` (installed: `~/.grinta/settings.json`;
source checkout: repository root). Runtime paths are resolved through
`backend/core/config/` — see [`backend/core/config/README.md`](../core/config/README.md).

## Optional PostgreSQL

PostgreSQL is **not** part of the default install. It appears only in optional
knowledge-base migration tooling under `knowledge_base/migrations/` when you
explicitly opt into a Postgres-backed knowledge store.

## Related docs

- Architecture durability layer: [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md)
- Contributor map (storage touch points): [`docs/CONTRIBUTOR_MAP.md`](../../docs/CONTRIBUTOR_MAP.md)
