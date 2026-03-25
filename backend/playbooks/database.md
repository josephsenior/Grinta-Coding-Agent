---
name: database
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /database
---

# Database setup

**Principle:** Simplest thing that works — usually **SQLite** for local dev unless the user needs a specific engine.

## Ask once

Offer **SQLite (dev)** vs **user-managed server** (Postgres, MySQL, Mongo, etc.). Do not assume a server is installed.

## Prefer lighter options when prototyping

| User says | Often start with |
|-----------|------------------|
| Postgres / MySQL | SQLite for dev, or their existing local instance |
| Mongo | Local Mongo or embedded doc store per stack |

## Snippets (reference)

**SQLite (Node):** `better-sqlite3` — open file, `CREATE TABLE IF NOT EXISTS`, parameterized queries.  
**Postgres (Node):** `pg` `Pool` — never hardcode passwords; use env vars.

## Rules

- No secrets in source; use env + system security rules.
- Parameterized queries only (SQL injection).
