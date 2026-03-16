---
name: React
type: knowledge
version: 1.0.0
agent: Orchestrator
triggers:
  - /react
  - useState(
  - useEffect(
---

# React Best Practices

## Hooks Patterns

### State Management
```tsx
// ✅ Good: Functional updates
setCount(prev => prev + 1);

// ❌ Bad: Direct state reference
setCount(count + 1);

// ✅ Good: Multiple related states
const [form, setForm] = useState({ name: '', email: '' });

// ✅ Good: Derived state (no useState needed)
const fullName = `${firstName} ${lastName}`;
```

### Effects
```tsx
// ✅ Good: Cleanup
useEffect(() => {
  const timer = setInterval(() => tick(), 1000);
  return () => clearInterval(timer);
}, []);

// ✅ Good: Dependencies
useEffect(() => {
  fetchData(userId);
}, [userId]);

// ❌ Bad: Missing dependencies (use ESLint!)
useEffect(() => {
  fetchData(userId);
}, []); // userId should be in deps
```

### Custom Hooks
```tsx
// ✅ Good: Reusable logic
function useFetch<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(url)
      .then(r => r.json())
      .then(setData)
      .finally(() => setLoading(false));
  }, [url]);

  return { data, loading };
}
```

## Component Patterns

### Composition over Props Drilling
```tsx
// ✅ Good: Context for shared state
const ThemeContext = createContext<Theme>('light');

// ✅ Good: Children prop
function Card({ children }: { children: React.ReactNode }) {
  return <div className="card">{children}</div>;
}
```

### Memoization
```tsx
// Use React.memo for expensive renders
const ExpensiveComponent = React.memo(({ data }) => {
  // Heavy computation
});

// Use useMemo for expensive calculations
const sortedList = useMemo(() =>
  items.sort((a, b) => a.value - b.value),
  [items]
);

// Use useCallback for stable function references
const handleClick = useCallback(() => {
  doSomething(id);
}, [id]);
```

## Common Pitfalls

❌ **Mutating state directly**
```tsx
// Bad
items.push(newItem);
setItems(items);

// Good
setItems([...items, newItem]);
```

❌ **Using index as key**
```tsx
// Bad
{items.map((item, i) => <div key={i}>{item}</div>)}

// Good
{items.map(item => <div key={item.id}>{item}</div>)}
```

❌ **Unnecessary re-renders**
```tsx
// Bad: Creates new object every render
<Child style={{ margin: 10 }} />

// Good: Define outside or use useMemo
const style = { margin: 10 };
<Child style={style} />
```
