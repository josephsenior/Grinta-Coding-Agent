---
name: database
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - postgresql
  - mongodb
  - /database
---

# Database Setup

**Core principle:** Simple first.

## Quick Decision

User mentions database? **Ask first:**

```
I can set up [DATABASE] in a few ways:

1. SQLite (Recommended for dev)
   - No installation, works immediately

2. Local [DATABASE]
   - You install locally, I create connection code

Which do you prefer?
```

## Lightweight Alternatives

**PostgreSQL** → SQLite
**MySQL** → SQLite or MariaDB
**MongoDB** → NeDB or local MongoDB
**Redis** → In-memory store or local Redis

## Examples

### SQLite (Node.js)
```javascript
// npm install better-sqlite3
const Database = require('better-sqlite3');
const db = new Database('dev.db');

db.exec(`CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL,
  email TEXT UNIQUE
)`);
```

### PostgreSQL Connection (User Installs)
```javascript
// npm install pg
const { Pool } = require('pg');
const pool = new Pool({
  host: 'localhost',
  database: 'myapp',
  user: 'postgres',
  password: 'password'
});
```

## Rules

**DON'T:**
- Assume a specific database is installed.

**DO:**
- Present options first.
- Recommend simplest (SQLite for dev).
