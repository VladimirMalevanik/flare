import { ApiDataProvider } from "./api-provider";
import { MockDataProvider } from "./mock-provider";
import type { FlareDataProvider } from "./provider";

export const dataProviderMode =
  process.env.NEXT_PUBLIC_DATA_PROVIDER === "api" ? "api" : "mock";

const mockProvider = new MockDataProvider();
export const dataProvider: FlareDataProvider =
  dataProviderMode === "api"
    ? new ApiDataProvider({
        baseUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
        fallback: mockProvider,
      })
    : mockProvider;

export function dataErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export * from "./types";
