# Flare frontend MVP

A standalone frontend for Flare, an AI second brain. It recreates the supplied Stitch direction with an intentionally small Next.js App Router codebase and a mock data provider.

## Run locally

```bash
npm install
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

- Click the floating capture bar or press Cmd/Ctrl+K on any page. One input accepts text, URLs, file metadata, and voice. Notes and URLs are detected automatically and appear immediately in Vault.
- Select a local file. Only name/type/size metadata is retained.
- Record audio where MediaRecorder is available. Otherwise the button creates a useful processing mock rather than doing nothing.
- Search and filter Vault, then choose items to inspect their facts, source content and related items.
- Select an insight and open its evidence source.
- Refresh after creating an item: local mock items persist in browser localStorage. Existing user items retain the same storage key.
- Switch light/dark from the sidebar or choose System in Settings. Preferences survive navigation and refresh.
- Configure, add, or reconnect a demo source. Changes are local; no external accounts are contacted.

## Current mock boundary

No backend, authentication, database, or AI calls are included. Current seeds live in `src/mocks/cupertino.ts` and `src/mocks/sources.ts`; user-created mock item metadata is stored under `flare-user-items-v1`. The UI accesses items, insights, and sources through `FlareDataProvider`. Voice capture produces a demo transcript/processing item; audio and file binaries are not persisted or uploaded. Notification delivery and retention policies are preferences only.

The UI follows the Cupertino Minimal simplified Stitch references with one token system for both themes. Inter is served locally under its OFL license. See [the design notes](docs/DESIGN_UPDATE.md) for reference decisions and intentional differences.

Integration details and the frontend contract are in [docs/INTEGRATION.md](docs/INTEGRATION.md) and [docs/API_CONTRACT.md](docs/API_CONTRACT.md).
