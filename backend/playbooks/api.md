---
name: API
type: knowledge
version: 2.0.0
agent: Orchestrator
triggers:
  - /api
---

# HTTP API patterns

Use when the user invokes **`/api`**. Apply workspace **SECURITY** (no secrets in responses/logs).

## FastAPI (Python) — skeleton

```python
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel

app = FastAPI()

class User(BaseModel):
    name: str
    email: str

@app.post("/users", status_code=201)
async def create_user(user: User):
    return {"id": 1, **user.model_dump()}

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    row = db.get(user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return row
```

**Dependencies:** `Depends` for DB/session per request; close resources in generator teardown.

## REST conventions

| Method | Typical use |
|--------|-------------|
| GET | Read |
| POST | Create |
| PUT/PATCH | Replace / partial update |
| DELETE | Remove |

**Status codes:** `200` OK, `201` created, `204` empty success, `400` validation, `401/403` authz, `404` missing, `422` body validation (FastAPI), `500` unexpected.

## Responses

Prefer **consistent JSON** shape for success and errors (stable `detail` / `code` fields) so clients can branch predictably.

## Pagination (list endpoints)

Return `items`, `total`, and `page` / `cursor` as appropriate; bound `limit` to avoid abuse.

## Express (Node) — minimal

```typescript
app.use(express.json());
app.post("/users", (req, res) => {
  const b = req.body;
  if (!b?.name) return res.status(400).json({ error: "name required" });
  res.status(201).json({ id: 1, ...b });
});
```

Validate input; never trust `req.body` for SQL — use parameterized queries or ORM.
