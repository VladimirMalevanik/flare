import type { AnalyticsEventInput } from "@/lib/data/provider";

export interface FlareViewState {
  current: string | null;
}

export function nextFlareViewEvent(
  state: FlareViewState,
  flareId: string,
  interactionId?: string,
): AnalyticsEventInput | null {
  if (!interactionId || state.current === flareId) return null;
  state.current = flareId;
  return { eventType: "voluntary_inspection", interactionId, flareId };
}

export function resetFlareView(state: FlareViewState): void {
  state.current = null;
}
