# Architecture

App Router layouts and route wrappers remain server components. The interactive `AppShell` owns navigation and the mobile drawer. `WorkspaceProvider` shares theme, density, capture state, and a data-refresh revision across the client features.

```
src/app        routes and shared layout
src/components shared UI and shell
src/features   capture, Insights, Vault, Sources, Settings interactions
src/lib/data   domain types and provider boundary
src/lib/storage browser preference persistence
src/mocks      seed data
```

UI components never import mock arrays. They call the singleton `dataProvider`, typed by `FlareDataProvider`. `MockDataProvider` merges immutable seed content with browser-only user items from localStorage. Its storage calls are guarded against SSR and parsing failure. It stores file metadata and audio-derived text only — never blobs or binary.

The existing `flare-user-items-v1` storage key is retained. Captures trigger a shared revision so lists and counts refresh without a page reload. Source configuration, profile, and preferences are also local demo state; they do not connect accounts or change backend policies.

One token system in `globals.css` handles light and dark appearance. System mode follows the operating-system preference. A shared native dialog provides expanded capture and detail/configuration overlays. `/` and the legacy `/dashboard` route redirect to `/insights`.

`ApiDataProvider` is an intentionally non-functional adapter stub. Keeping it beside `MockDataProvider` makes the future seam explicit without imposing a backend design today.
