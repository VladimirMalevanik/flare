import { apiBaseUrl, isLocalDemo } from "@/lib/auth/session";
import { ApiDataProvider } from "./api-provider";
import { MockDataProvider } from "./mock-provider";
import type { FlareDataProvider } from "./provider";

export const dataProviderMode =
  isLocalDemo ? "mock" : "api";

const mockProvider = new MockDataProvider();
export const dataProvider: FlareDataProvider =
  dataProviderMode === "api"
    ? new ApiDataProvider({
        baseUrl: apiBaseUrl,
        fallback: mockProvider,
      })
    : mockProvider;

export function dataErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export * from "./types";
