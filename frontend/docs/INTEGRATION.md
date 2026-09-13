# Backend integration guide

1. Set `NEXT_PUBLIC_DATA_PROVIDER=api` and point `NEXT_PUBLIC_API_URL` at the FastAPI origin. Use `mock` to run the standalone demo.
2. `ApiDataProvider` maps backend DTOs to the frontend domain types; backend shapes do not leak into components.
3. Notes use the real `GET`, `POST`, and `DELETE /items` routes. A successful capture reloads the recent list from PostgreSQL.
4. Flares read `GET /flares` and `GET /flares/{id}` with strict DTO validation and no mock fallback.
5. Analyze uses `POST /analyze` plus `GET /analysis-runs/{id}` with idempotency and bounded polling.
6. GitHub uses `/integrations/github` for authorization, status, repository listing/selection, and disconnect. The remaining Sources catalog is demo metadata.
7. URL, file, and audio capture report a clear unsupported-operation error in API mode. Do not silently save those records locally.
8. Keep processing states explicit when file/audio ingestion is added; creation may finish asynchronously.

The contract is defined in [API_CONTRACT.md](API_CONTRACT.md). Explicit development mock mode remains independent; its three Flare fixtures use the same taxonomy and exact source excerpts.

Cupertino update: `/` and `/dashboard` redirect to `/insights`. `WorkspaceProvider` owns shared capture, theme, density, and a revision counter that refreshes item consumers after capture. Sources uses demo catalog records plus live GitHub connection state. Preference toggles never call external services.

Flares show statement, optional action, reason and exact evidence in the existing
layout. Filters are Reminder, Warning and Recommendation. New sources and text
imports enqueue background analysis automatically; explicit Analyze still creates
a separate bounded run when the user wants one.

Provider regression checks: `node --test frontend/tests/flare-provider.test.cjs` from the repository root.
