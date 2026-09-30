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
  return fallback;
}

export * from "./types";
