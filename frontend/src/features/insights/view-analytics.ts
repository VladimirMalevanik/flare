import type { AnalyticsEventInput } from "@/lib/data/provider";

export interface FlareViewState {
  current: string | null;
}

export function nextFlareViewEvent(
  state: FlareViewState,
  flareId: string,
): AnalyticsEventInput | null {
  if (state.current === flareId) return null;
  state.current = flareId;
  return {
    eventType: "flare_viewed",
    targetType: "flare",
    targetId: flareId,
    metadata: { source: "insights_feed" },
  };
}

export function resetFlareView(state: FlareViewState): void {
  state.current = null;
}
