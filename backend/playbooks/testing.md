---
name: Testing
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
    - /testing
    - pytest
    - jest
    - unittest
    - vitest
---

# Testing Best Practices

## Python (pytest)

### Basic Structure
```python
# test_calculator.py
import pytest

def test_add():
    assert add(2, 3) == 5

def test_divide_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
```

### Fixtures
```python
@pytest.fixture
def db_session():
    session = create_session()
    yield session
    session.close()

def test_user_creation(db_session):
    user = User(name="John")
    db_session.add(user)
    assert user.id is not None
```

### Parametrize
```python
@pytest.mark.parametrize("input,expected", [
    (2, 4),
    (3, 9),
    (4, 16),
])
def test_square(input, expected):
    assert square(input) == expected
```

### Mocking
```python
from unittest.mock import Mock, patch

def test_api_call():
    with patch('requests.get') as mock_get:
        mock_get.return_value.json.return_value = {'data': 'test'}
        result = fetch_data('url')
        assert result == {'data': 'test'}
```

## JavaScript/TypeScript (Jest/Vitest)

### Basic Structure
```typescript
// calculator.test.ts
import { describe, it, expect } from 'vitest';

describe('Calculator', () => {
  it('adds two numbers', () => {
    expect(add(2, 3)).toBe(5);
  });

  it('throws on divide by zero', () => {
    expect(() => divide(1, 0)).toThrow();
  });
});
```

### React Testing
```typescript
import { render, screen, fireEvent } from '@testing-library/react';

test('button click updates count', () => {
  render(<Counter />);
  const button = screen.getByRole('button');

  fireEvent.click(button);

  expect(screen.getByText('Count: 1')).toBeInTheDocument();
});
```

### Mocking
```typescript
import { vi } from 'vitest';

test('calls API', async () => {
  const mockFetch = vi.fn().mockResolvedValue({ data: 'test' });
  global.fetch = mockFetch;

  await fetchData('url');

  expect(mockFetch).toHaveBeenCalledWith('url');
});
```

## Best Practices

### AAA Pattern
```python
def test_user_login():
    # Arrange
    user = User(email="test@example.com")

    # Act
    result = login(user)

    # Assert
    assert result.success is True
```

### Test Naming
```python
# ✅ Good: Descriptive
def test_user_cannot_login_with_invalid_password():
    ...

# ❌ Bad: Vague
def test_login():
    ...
```

### One Assertion Focus
```python
# ✅ Good: Tests one thing
def test_user_email_is_lowercase():
    user = User(email="TEST@Example.com")
    assert user.email == "test@example.com"

# ❌ Bad: Tests multiple things
def test_user():
    user = User(email="TEST@Example.com")
    assert user.email == "test@example.com"
    assert user.is_active is True
    assert len(user.tokens) == 1
```

### Test Independence
```python
# ✅ Good: Independent tests
def test_create_user():
    user = create_user()
    assert user.id is not None

def test_delete_user():
    user = create_user()  # Own setup
    delete_user(user.id)
    assert get_user(user.id) is None
```
