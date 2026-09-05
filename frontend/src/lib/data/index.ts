import { MockDataProvider } from "./mock-provider";
import type { FlareDataProvider } from "./provider";
export const dataProvider: FlareDataProvider = new MockDataProvider();
export * from "./types";
