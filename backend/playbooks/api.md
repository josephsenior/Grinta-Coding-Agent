---
name: API
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - api
  - rest
  - endpoint
  - fastapi
  - express
  - flask
---

# API/REST Best Practices

## FastAPI (Python)

### Basic Structure
```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

class User(BaseModel):
    name: str
    email: str

@app.post("/users", status_code=201)
async def create_user(user: User):
    # Validation happens automatically via Pydantic
    return {"id": 1, **user.dict()}

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
```

### Dependency Injection
```python
from fastapi import Depends

def get_db():
    db = Database()
    try:
        yield db
    finally:
        db.close()

@app.get("/items")
async def list_items(db: Database = Depends(get_db)):
    return db.query(Item).all()
```

### Error Handling
```python
@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"error": str(exc)}
    )
```

## Express (Node.js)

### Basic Structure
```typescript
import express from 'express';

const app = express();
app.use(express.json());

interface User {
  name: string;
  email: string;
}

app.post('/users', (req, res) => {
  const user: User = req.body;

  if (!user.name || !user.email) {
    return res.status(400).json({ error: 'Missing fields' });
  }

  res.status(201).json({ id: 1, ...user });
});

app.get('/users/:id', (req, res) => {
  const user = db.getUser(req.params.id);

  if (!user) {
    return res.status(404).json({ error: 'User not found' });
  }

  res.json(user);
});
```

### Middleware
```typescript
// Request validation middleware
const requireWorkspace = (req, res, next) => {
  const workspaceId = req.headers['x-workspace-id'];

  if (!workspaceId) {
    return res.status(400).json({ error: 'Missing workspace id' });
  }

  req.workspaceId = workspaceId;
  next();
};

app.get('/workspace', requireWorkspace, (req, res) => {
  res.json({ workspaceId: req.workspaceId });
});
```

## REST Conventions

### HTTP Methods
```
GET    /users      → List all users
GET    /users/:id  → Get specific user
POST   /users      → Create user
PUT    /users/:id  → Replace user (full update)
PATCH  /users/:id  → Update user (partial)
DELETE /users/:id  → Delete user
```

### Status Codes
```
200 OK           → Successful GET/PUT/PATCH
201 Created      → Successful POST
204 No Content   → Successful DELETE
400 Bad Request  → Validation error
401 Unauthorized → Missing/invalid auth
403 Forbidden    → Auth OK, but not allowed
404 Not Found    → Resource doesn't exist
500 Server Error → Internal error
```

### Response Structure
```json
// ✅ Good: Consistent structure
{
  "data": { "id": 1, "name": "John" },
  "error": null
}

// Error response
{
  "data": null,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Email is required",
    "fields": ["email"]
  }
}
```

## Common Patterns

### Pagination
```python
@app.get("/items")
async def list_items(page: int = 1, per_page: int = 20):
    offset = (page - 1) * per_page
    items = db.query(Item).offset(offset).limit(per_page).all()
    total = db.query(Item).count()

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page
    }
```

### Filtering/Sorting
```python
@app.get("/items")
async def list_items(
    status: Optional[str] = None,
    sort_by: str = "created_at",
    order: str = "desc"
):
    query = db.query(Item)

    if status:
        query = query.filter(Item.status == status)

    if order == "desc":
        query = query.order_by(Item[sort_by].desc())
    else:
        query = query.order_by(Item[sort_by].asc())

    return query.all()
```
