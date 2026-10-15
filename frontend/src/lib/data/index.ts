import { apiBaseUrl, isLocalDemo } from "@/lib/auth/session";
import { ApiDataProvider } from "./api-provider";
import { ProductionCatalogProvider } from "./catalog-provider";
import { MockDataProvider } from "./mock-provider";
import type { FlareDataProvider } from "./provider";

export const dataProviderMode = isLocalDemo ? "mock" : "api";

export const dataProvider: FlareDataProvider =
  dataProviderMode === "api"
    ? new ApiDataProvider({
        baseUrl: apiBaseUrl,
        fallback: new ProductionCatalogProvider(),
      })
    : new MockDataProvider();

export function dataErrorMessage(error: unknown, fallback: string): string {
  const failure = error as { status?: number; code?: string } | null;
  if (failure?.status === 401) return "errorSession";
  if (failure?.status === 403) return "errorPermission";
  if (failure?.status === 429) return "errorRateLimit";
  if (failure?.code === "request_outcome_unknown") return "errorUnconfirmed";
  if (failure?.code === "request_timeout") return "errorTimeout";
  if (failure?.status === 409 && failure.code === "Item changed since it was loaded; reload it and retry") return "errorVersionConflict";
  return fallback;
}

export * from "./types";
