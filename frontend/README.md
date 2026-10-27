# frontend/

Next.js 16 (App Router, Cache Components) + React 19 + TypeScript. Styling uses CSS Modules on top of the HABITA design tokens in `src/styles/tokens.css`. No UI framework.

## Run

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000, expects the backend on :8000
```

`frontend/.env.local` (git-ignored):

```
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=<browser key: HTTP-referrer restricted; Maps JavaScript API + Places API (New)>
```

Without the browser key, the map shows a designed "not configured" state and address entry falls back to free text, which the backend resolves.

## Checks

```bash
npm run typecheck      # next typegen + tsc
npm run lint
npm test               # vitest unit tests
npm run build
```

## Layout

```
src/
  app/                         routes: / (address entry), /property/[propertyId] (workspace)
  styles/tokens.css            design tokens: colour, type, spacing, radius, elevation, motion
  components/ui/               Button, Badge, Notice, Section, Skeleton, Spinner, Icon
  components/shell/TopBar      identity + module navigation
  features/property/           address search, workspace, map, jurisdiction view, API client
  lib/                         config, API client, Google Maps loader + map style
```

`AGENTS.md` is maintained by Next.js itself (`next dev` re-creates it).
