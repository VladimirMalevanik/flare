# Flare frontend MVP

The Next.js client for Flare, an AI second brain. It supports a real FastAPI/PostgreSQL note flow and retains a mock mode for standalone UI work.

## Run locally

```bash
npm install
npm run dev
```

To connect the local backend, create `.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_DATA_PROVIDER=api
```

Then run:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Routes: `/insights`, `/vault`, `/sources`, and `/settings`. Both `/` and the legacy `/dashboard` redirect to `/insights`.

For a production check:

```bash
npm run lint
npm run build
npm start
```

## What to try

- In API mode, click the floating capture bar or press Cmd/Ctrl+K on any page to save a note in PostgreSQL.
- In mock mode, the same input also demonstrates URL detection, local file metadata, and voice capture. File binaries and recorded audio are not retained.
- Search and filter Vault, then choose items to inspect their facts, source content and related items.
- Select an insight and open its evidence source.
- In API mode, create a note and refresh: it persists in PostgreSQL and can be deleted from its Vault detail.
- In mock mode, captured items persist in browser localStorage.
- Switch light/dark from the sidebar or choose System in Settings. Preferences survive navigation and refresh.
- Configure, add, or reconnect a demo source. Changes are local; no external accounts are contacted.

## Current integration boundary

With `NEXT_PUBLIC_DATA_PROVIDER=api`, note creation, listing, detail lookup, and deletion use FastAPI. The development backend supplies a fixed local workspace identity; production authentication is still pending. URL, file, and audio ingestion are not implemented by the API yet. Insights and Sources remain demo data from `src/mocks`, and notification delivery and retention policies are preferences only.

With `NEXT_PUBLIC_DATA_PROVIDER=mock`, the original browser-only demo remains available. User-created mock item metadata is stored under `flare-user-items-v1`; audio and file binaries are never persisted.

The UI follows the Cupertino Minimal simplified Stitch references with one token system for both themes. Inter is served locally under its OFL license. See [the design notes](docs/DESIGN_UPDATE.md) for reference decisions and intentional differences.

Integration details and the frontend contract are in [docs/INTEGRATION.md](docs/INTEGRATION.md) and [docs/API_CONTRACT.md](docs/API_CONTRACT.md).
