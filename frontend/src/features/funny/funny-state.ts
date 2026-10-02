export type FunnyPhase = "idle" | "armed" | "shaken" | "thinking" | "complete" | "empty" | "error";
export interface FunnyRitualState {
  phase: FunnyPhase;
  requestId: number;
  shakes: number;
}
export const INITIAL_FUNNY_RITUAL: FunnyRitualState = { phase: "idle", requestId: 0, shakes: 0 };
export const REQUIRED_SHAKES = 4;

export function advanceFunnyShake(state: FunnyRitualState): FunnyRitualState {
  if (state.phase !== "armed" && state.phase !== "thinking") return state;
  const shakes = Math.min(state.shakes + 1, 999);
  return { ...state, shakes, phase: state.phase === "armed" && shakes >= REQUIRED_SHAKES ? "shaken" : state.phase };
}

export function funnyMessage(state: FunnyRitualState): string {
  if (state.phase === "armed") return ["Nah, dude. Shake the ball.", "Keep shaking. The vibes are warming up.", "Shake, shake. Almost there.", "One more. Make it legendary."][Math.min(state.shakes, 3)];
  if (state.phase === "shaken") return "The ball has spoken. Starting your analysis…";
  if (state.phase === "thinking") return ["Keep shaking. Flare is reading your sources…", "Shake it like you mean it. Still thinking…", "Consulting the evidence, not the universe…"][state.shakes % 3];
  if (state.phase === "complete") return "Fresh Flares have entered the chat.";
  if (state.phase === "empty") return "The ball checked. No new Flares this time.";
  if (state.phase === "error") return "The ball hit a snag. Check the message below.";
  return "Capture an idea. Question the universe later.";
}

// Count substantial direction changes, not a normal drag or tiny pointer jitter.
export interface ShakeTracker { x: number; y: number; direction: number; axis: "x" | "y" | null; time: number }
export function beginShake(x: number, y: number, time: number): ShakeTracker {
  return { x, y, direction: 0, axis: null, time };
}
export function moveShake(previous: ShakeTracker, x: number, y: number, time: number): { tracker: ShakeTracker; shake: boolean } {
  if (time - previous.time > 900) return { tracker: beginShake(x, y, time), shake: false };
  const dx = x - previous.x;
  const dy = y - previous.y;
  const axis = previous.axis ?? (Math.abs(dx) >= Math.abs(dy) ? "x" : "y");
  const delta = axis === "x" ? dx : dy;
  if (Math.abs(delta) < 18) return { tracker: previous, shake: false };
  const direction = Math.sign(delta);
  return {
    tracker: { x, y, direction, axis, time },
    shake: previous.direction !== 0 && direction !== previous.direction,
  };
}

// Consume a gesture once even when React repeats effects or pointer events arrive rapidly.
export function consumeFunnyRequest(state: FunnyRitualState, consumed: number, eligible: boolean): number | null {
  return eligible && state.phase === "shaken" && state.requestId > consumed ? state.requestId : null;
}
