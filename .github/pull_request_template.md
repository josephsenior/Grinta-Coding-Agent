# Pull Request

## What and Why

Describe what changed and why this is needed.

## Risk Assessment

- Risk level: [ ] low [ ] medium [ ] high
- Security impact: [ ] none [ ] yes (describe below)
- Backward compatibility impact: [ ] none [ ] yes (describe below)

If any impact is "yes", explain:

## Test Evidence

List exact commands you ran and the result.

```text
# Example (matches required Linux/Windows gates):
uv run pytest backend/tests/unit -q
# Full tree (pytest.ini testpaths; slower, optional before merge):
# uv run pytest -q
uv run mypy --config-file mypy.ini
```

## Docs and Changelog

- [ ] Documentation updated (or not needed)
- [ ] `CHANGELOG.md` updated (or not needed)

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update
- [ ] Refactor / maintenance
- [ ] Security fix

## Related Issues

Fixes #(issue number)
Related to #(issue number)
