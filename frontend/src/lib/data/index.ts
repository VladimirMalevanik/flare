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
  return error instanceof Error && error.message ? error.message : fallback;
}

export * from "./types";
