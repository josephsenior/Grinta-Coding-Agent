---
name: typescript
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /typescript
  - /ts
---

# TypeScript discipline

Use when the user invokes **`/typescript`** or **`/ts`**, or when writing/editing `.ts`/`.tsx` files.

## Principles

1. **Strict Types**: Never use `any` unless absolutely necessary (use `unknown` if the shape is truly unknown).
2. **Interfaces over Types**: Prefer `interface` for object shapes and class contracts to allow declaration merging and better error messages. Use `type` for unions and intersections.
3. **Nullability**: Use strict null checks. Prefer optional chaining (`?.`) and nullish coalescing (`??`) to guard against `undefined` or `null`.
4. **Immutability**: Prefer `readonly` arrays (`ReadonlyArray<T>`) and properties when data shouldn't be mutated.

## Code Patterns

```typescript
// Good: Clear interfaces, exhaustive matching
interface User {
  id: string;
  name: string;
  email?: string;
}

// Good: Type guard functions
function isUser(obj: unknown): obj is User {
  return typeof obj === 'object' && obj !== null && 'id' in obj && 'name' in obj;
}

// Good: Record for dictionaries
const config: Record<string, boolean> = {
  featureX: true,
};
```

## Anti-Patterns to Avoid

- ❌ `as any` or `<any>` casting to bypass the compiler.
- ❌ Non-null assertions (`!`) unless you have statically verified the presence of the value just prior.
- ❌ Deeply nested object types inline. Extract them to interfaces.

## Validation
Always run `tsc --noEmit` to verify type strictness after modifying `.ts` files, or use the project's specific lint/typecheck command.
