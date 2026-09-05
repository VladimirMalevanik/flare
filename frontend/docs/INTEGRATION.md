# Backend integration guide

1. Do not rewrite the existing UI or change product layout unless an integration requirement demands it.
2. Implement `ApiDataProvider` in `src/lib/data/api-provider.ts` against the actual backend.
3. Map backend DTOs to the frontend domain types in `src/lib/data/types.ts`; do not leak backend DTO shapes into components.
4. Change only `src/lib/data/index.ts` to select `ApiDataProvider` when the adapter is ready.
5. Preserve `MockDataProvider` until integration tests are passing.
6. Verify shared capture from every page, Vault grid/list/search/filter/detail, Insights selection and evidence-to-source navigation, Sources configuration, and Settings theme/preferences.
7. Treat processing states explicitly: file/audio ingestion may complete after item creation.

The contract is defined in [API_CONTRACT.md](API_CONTRACT.md). The mock provider provides the expected behaviors for every operation.

Cupertino update: `/` and `/dashboard` redirect to `/insights`. `WorkspaceProvider` owns shared capture, theme, density, and a revision counter that refreshes item consumers after capture. Sources now use `listSources` and `saveSource`; both remain mocked. Preference toggles never call external services.
