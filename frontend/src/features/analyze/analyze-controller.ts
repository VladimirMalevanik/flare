import type { AnalysisRun } from "@/lib/data/types";
import type { FlareDataProvider } from "@/lib/data/provider";

export type AnalyzeState = { busy: boolean; run: AnalysisRun | null; message: string; error: boolean };
const initial: AnalyzeState = { busy: false, run: null, message: "", error: false };
const retryable = new Set(["rate_limited", "timeout", "network", "provider_transient", "provider_server", "lease_expired"]);
const requestFailureMessages: Record<string, string> = {
  no_context: "No project context yet. Add a note or import a source before analyzing.",
  no_ready_context: "Your saved context is still being prepared. Try again shortly.",
  context_too_large: "Your saved context is too large for the current analysis limit.",
  request_budget_exceeded: "Flare found project context, but it could not fit into this analysis run.",
  unsupported_context: "Your saved sources are not supported by Analyze yet.",
};
export function failureMessage(code: string | null) {
  if (retryable.has(code ?? "")) return "Analysis could not finish. Try again.";
  if (["source_invalid", "authorization_revoked"].includes(code ?? "")) return "Context or access changed. Check your Notes and permissions before retrying.";
  return "Analysis could not finish. Check configuration with your workspace administrator before retrying.";
}
function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new Error("cancelled")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
  });
}

export class AnalyzeController {
  private state = initial;
  private generation = 0;
  private abort: AbortController | null = null;
  private pendingKey: string | null = null;
  constructor(
    private provider: Pick<FlareDataProvider, "startAnalysis" | "getAnalysisRun">,
    private publish: (state: AnalyzeState) => void,
    private complete: () => void,
    private sleep = wait,
    private key = () => crypto.randomUUID(),
    private maxPolls = 40,
  ) {}
  private update(next: AnalyzeState) { this.state = next; this.publish(next); }
  dispose = () => { this.generation++; this.abort?.abort(); this.abort = null; this.state = { ...this.state, busy: false }; };
  start = async () => {
    if (this.state.busy) return;
    const generation = ++this.generation;
    const abort = new AbortController();
    this.abort = abort;
    const deadline = setTimeout(() => abort.abort(), 300_000);
    let run = this.state.run;
    this.update({ busy: true, run, error: false, message: "Analyzing project context…" });
    const live = () => generation === this.generation && !abort.signal.aborted;
    try {
      // Unknown POST outcome reuses the key. Terminal retries get a new key.
      if (!run || ["completed", "failed"].includes(run.status)) {
        this.pendingKey ??= this.key();
        run = await this.provider.startAnalysis(this.pendingKey, abort.signal);
        if (!live()) return;
        this.pendingKey = null;
      }
      for (let count = 0; live(); count++) {
        if (run.status === "completed") {
          this.complete();
          this.update({ busy: false, run, error: false, message: run.flareIds.length ? "Analysis complete. Flares refreshed." : "Analysis complete. No new Flares found." });
          return;
        }
        if (run.status === "failed") {
          this.update({ busy: false, run, error: true, message: failureMessage(run.error) });
          return;
        }
        this.update({ busy: true, run, error: false, message: run.stage === "flare_generation" ? "Generating Flares…" : "Analyzing project context…" });
        if (count >= this.maxPolls) break;
        await this.sleep(Math.min(1000 * 1.5 ** count, 10000), abort.signal);
        if (!live()) return;
        run = await this.provider.getAnalysisRun(run.id, abort.signal);
      }
      if (generation === this.generation) this.update({ busy: false, run, error: true, message: "Analysis is still pending. Check status again shortly." });
    } catch (error) {
      if (generation !== this.generation) return;
      const status = (error as { status?: number }).status;
      const code = (error as { code?: string }).code;
      if (status && status >= 400 && status < 500) this.pendingKey = null;
      this.update({ busy: false, run, error: true, message: status === 422
        ? requestFailureMessages[code ?? ""] ?? "Analysis could not accept this request. Try again shortly."
        : status === 403 ? "Only workspace owners and editors can analyze context."
        : status === 409 && code === "daily_limit"
          ? "Today’s insight slot is already used or scheduled. The next run is available tomorrow."
        : status === 409 && code === "selection_changed"
          ? "Project context changed while analysis was starting. Try again now."
        : status === 409 ? "Analysis request conflicted with another change. Try again."
        : "Analysis status is unavailable. Try again to check this request." });
    } finally {
      clearTimeout(deadline);
      if (generation === this.generation && this.state.busy) {
        this.update({ busy: false, run, error: true, message: "Analysis is still pending. Check status again shortly." });
      }
    }
  };

  resume = async (runId: string) => {
    if (this.state.busy) return;
    const generation = ++this.generation;
    const abort = new AbortController();
    this.abort = abort;
    this.update({ busy: true, run: null, error: false, message: "Loading today’s insight…" });
    try {
      const run = await this.provider.getAnalysisRun(runId, abort.signal);
      if (generation !== this.generation || abort.signal.aborted) return;
      if (run.status === "completed") {
        this.complete();
        this.update({ busy: false, run, error: false, message: run.flareIds.length
          ? "Today’s insight is complete."
          : "Today’s insight completed with no new Flares." });
        return;
      }
      if (run.status === "failed") {
        this.update({ busy: false, run, error: true, message: failureMessage(run.error) });
        return;
      }
      this.state = { busy: false, run, error: false, message: "" };
      await this.start();
    } catch {
      if (generation === this.generation) {
        this.update({ busy: false, run: null, error: true, message: "Today’s insight status is unavailable." });
      }
    }
  };
}
