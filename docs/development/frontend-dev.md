# Frontend Development

The OneSearch frontend is a React 18 + TypeScript single-page application.

## Getting Started

### Prerequisites

- Node.js 18 or later
- npm (comes with Node.js)

### Initial Setup

```bash
git clone https://github.com/demigodmode/OneSearch.git
cd OneSearch/frontend
```

Install dependencies:

```bash
npm install
```

### Start Development Server

```bash
npm run dev
```

The dev server runs at http://localhost:5173 and proxies API requests to the backend at http://localhost:8000.

Make sure the backend is running separately for full functionality.

---

## Project Structure

```
frontend/
├── src/
│   ├── main.tsx             # Entry point (renders App)
│   ├── App.tsx              # Router setup + TanStack Query provider
│   ├── pages/               # Page components
│   │   ├── SearchPage.tsx   # Main search (/)
│   │   ├── DocumentPage.tsx # Document preview (/document/:id)
│   │   └── admin/
│   │       ├── SourcesPage.tsx   # Source management
│   │       └── StatusPage.tsx    # Indexing status
│   ├── components/          # Reusable components
│   │   ├── SearchBox.tsx
│   │   ├── FilterPanel.tsx
│   │   ├── ResultCard.tsx
│   │   ├── SourceForm.tsx
│   │   ├── SourceTable.tsx
│   │   └── ui/              # shadcn/ui components
│   ├── lib/                 # Utilities
│   │   ├── api.ts           # API client functions
│   │   └── utils.ts         # Helper functions
│   ├── types/               # TypeScript types
│   │   └── api.ts           # API interfaces
│   └── index.css            # Global styles (Tailwind)
├── public/                  # Static assets
├── package.json
├── tsconfig.json            # TypeScript config
├── vite.config.ts           # Vite config
└── tailwind.config.js       # Tailwind config
```

---

## Tech Stack

**React 18** - UI library with hooks and functional components

**TypeScript** - Type safety catches bugs early

**Vite** - Fast dev server and build tool

**TanStack Query** (React Query) - Server state management, caching, refetching

**React Router** - Client-side routing

**shadcn/ui** - Accessible UI components (copied into project, not npm deps)

**Tailwind CSS** - Utility-first styling

**Lucide React** - Icon library

---

## Development Workflow

### Making Changes

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature
   ```

2. **Make your changes** - Edit files in `src/`

3. **Check for errors:**
   ```bash
   npm run lint
   npm run build
   ```

4. **Commit and push:**
   ```bash
   git add .
   git commit -m "add feature description"
   git push origin feature/your-feature
   ```

5. **Create a pull request**

### Adding Dependencies

```bash
npm install package-name
```

Always commit `package-lock.json` after adding dependencies.

---

## Key Concepts

### State Management

OneSearch uses **TanStack Query** for server state (search results, sources, status) and **React hooks** for local UI state.

**Server state example:**

```typescript
import { useQuery } from '@tanstack/react-query';
import { fetchSources } from '@/lib/api';

function SourcesPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['sources'],
    queryFn: fetchSources,
    refetchInterval: 30000  // Auto-refresh every 30s
  });

  if (isLoading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;

  return <SourceTable sources={data} />;
}
```

**Local state example:**

```typescript
function SearchBox() {
  const [query, setQuery] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // Do something with query
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
    </form>
  );
}
```

**Why this approach:**
- TanStack Query handles caching, refetching, and loading states automatically
- No need for global state (Redux, Zustand, etc.)
- Simple and performant

### API Client

API calls live in `src/lib/api.ts`. Each function wraps `fetch`:

```typescript
export async function fetchSources(): Promise<Source[]> {
  const response = await fetch('/api/sources');
  if (!response.ok) {
    throw new Error('Failed to fetch sources');
  }
  return response.json();
}

export async function createSource(source: SourceCreate): Promise<Source> {
  const response = await fetch('/api/sources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(source),
  });
  if (!response.ok) {
    throw new Error('Failed to create source');
  }
  return response.json();
}
```

**Mutations** for writes:

```typescript
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createSource } from '@/lib/api';

function SourceForm() {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: createSource,
    onSuccess: () => {
      // Invalidate sources query to trigger refetch
      queryClient.invalidateQueries({ queryKey: ['sources'] });
    },
  });

  const handleSubmit = (data: SourceCreate) => {
    mutation.mutate(data);
  };

  return <form onSubmit={handleSubmit}>...</form>;
}
```

### Routing

React Router handles navigation:

```typescript
// App.tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<SearchPage />} />
        <Route path="/document/:id" element={<DocumentPage />} />
        <Route path="/admin">
          <Route path="sources" element={<SourcesPage />} />
          <Route path="status" element={<StatusPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
```

Navigate programmatically:

```typescript
import { useNavigate } from 'react-router-dom';

function ResultCard({ result }) {
  const navigate = useNavigate();

  return (
    <div onClick={() => navigate(`/document/${result.id}`)}>
      {result.title}
    </div>
  );
}
```

### Components

Components are functional with hooks. Keep them small and focused.

**Good component:**

```typescript
interface SearchBoxProps {
  onSearch: (query: string) => void;
}

function SearchBox({ onSearch }: SearchBoxProps) {
  const [query, setQuery] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSearch(query);
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search..."
      />
      <button type="submit">Search</button>
    </form>
  );
}
```

**Extract logic into custom hooks:**

```typescript
function useDebounce(value: string, delay: number) {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}

// Use it
function SearchPage() {
  const [query, setQuery] = useState('');
  const debouncedQuery = useDebounce(query, 300);

  // Search with debouncedQuery
}
```

### Styling

OneSearch uses Tailwind CSS for styling:

```typescript
function Button({ children, onClick }) {
  return (
    <button
      onClick={onClick}
      className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
    >
      {children}
    </button>
  );
}
```

**shadcn/ui components** provide consistent styling:

```typescript
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

function Form() {
  return (
    <div>
      <Input placeholder="Enter name..." />
      <Button>Submit</Button>
    </div>
  );
}
```

These components are **copied into your project** (not npm dependencies), so you can customize them.

---

## Building for Production

Build the production bundle:

```bash
npm run build
```

Output goes to `dist/`. This is what gets deployed in the Docker image.

Preview the production build locally:

```bash
npm run preview
```

---

## Common Tasks

### Adding a New Page

1. Create component in `src/pages/`
2. Add route in `App.tsx`
3. Add navigation link if needed

Example:

```typescript
// pages/SettingsPage.tsx
export function SettingsPage() {
  return <div>Settings</div>;
}

// App.tsx
<Route path="/settings" element={<SettingsPage />} />
```

### Adding a New API Endpoint

1. Define TypeScript types in `src/types/api.ts`
2. Add API function in `src/lib/api.ts`
3. Use with TanStack Query in components

### Adding a shadcn/ui Component

```bash
npx shadcn-ui@latest add button
npx shadcn-ui@latest add input
npx shadcn-ui@latest add dialog
```

This copies the component into `src/components/ui/`.

---

## TypeScript Tips

Always define types for props:

```typescript
interface CardProps {
  title: string;
  onClick?: () => void;
}

function Card({ title, onClick }: CardProps) {
  // ...
}
```

Use interfaces from `src/types/api.ts` for API data:

```typescript
import { Source, SearchResult } from '@/types/api';

function ResultList({ results }: { results: SearchResult[] }) {
  // ...
}
```

Let TypeScript infer when obvious:

```typescript
// Good - type is obvious
const [count, setCount] = useState(0);

// Unnecessary
const [count, setCount] = useState<number>(0);
```

---

## Debugging

**React DevTools** - Install the browser extension to inspect component state.

**Console logging:**

```typescript
console.log('Search query:', query);
console.log('Results:', results);
```

**Network tab** - Check API requests in browser DevTools.

**TanStack Query DevTools:**

```typescript
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

function App() {
  return (
    <>
      {/* Your app */}
      <ReactQueryDevtools />
    </>
  );
}
```

Shows query status, cache, and refetches in the browser.

---

## Code Style

**Formatting** - ESLint and Prettier are configured. Run:

```bash
npm run lint
```

**Component naming** - PascalCase for components, camelCase for functions:

```typescript
function SearchPage() { }  // Component
function formatDate() { }  // Helper function
```

**File naming** - PascalCase for component files: `SearchPage.tsx`, `ResultCard.tsx`

---

## Performance Tips

**Memoize expensive computations:**

```typescript
import { useMemo } from 'react';

function ResultList({ results }) {
  const sortedResults = useMemo(
    () => results.sort((a, b) => b.score - a.score),
    [results]
  );

  return <div>{sortedResults.map(...)}</div>;
}
```

**Lazy load routes:**

```typescript
import { lazy, Suspense } from 'react';

const SourcesPage = lazy(() => import('./pages/admin/SourcesPage'));

function App() {
  return (
    <Suspense fallback={<div>Loading...</div>}>
      <Route path="/admin/sources" element={<SourcesPage />} />
    </Suspense>
  );
}
```

**Debounce search input** - Already implemented in SearchPage.

---

## Troubleshooting

### Build errors

Clear cache and reinstall:

```bash
rm -rf node_modules package-lock.json
npm install
```

### TypeScript errors

Check types:

```bash
npx tsc --noEmit
```

### Vite dev server issues

Restart the server:

```bash
# Ctrl+C to stop
npm run dev
```

### API proxy not working

Check `vite.config.ts`:

```typescript
export default defineConfig({
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
```

Make sure backend is running on port 8000.

---

## Next Steps

- [Architecture](architecture.md) - Understand the overall system
- [Backend Development](backend-dev.md) - Work on the backend
- [Contributing](contributing.md) - Contribution guidelines
