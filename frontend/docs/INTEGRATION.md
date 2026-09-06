# Backend integration guide

1. Set `NEXT_PUBLIC_DATA_PROVIDER=api` and point `NEXT_PUBLIC_API_URL` at the FastAPI origin. Use `mock` to run the standalone demo.
2. `ApiDataProvider` maps backend DTOs to the frontend domain types; backend shapes do not leak into components.
3. Notes use the real `GET`, `POST`, and `DELETE /items` routes. A successful capture reloads the recent list from PostgreSQL.
4. Sources and Insights use `MockDataProvider` as a temporary fallback while those API routes are not implemented.
5. URL, file, and audio capture report a clear unsupported-operation error in API mode. Do not silently save those records locally.
6. Keep processing states explicit when file/audio ingestion is added; creation may finish asynchronously.

The contract is defined in [API_CONTRACT.md](API_CONTRACT.md). The mock provider remains available for every operation.

Cupertino update: `/` and `/dashboard` redirect to `/insights`. `WorkspaceProvider` owns shared capture, theme, density, and a revision counter that refreshes item consumers after capture. Sources now use `listSources` and `saveSource`; both remain mocked. Preference toggles never call external services.
