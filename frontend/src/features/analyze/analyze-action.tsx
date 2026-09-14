"use client";
import { useEffect, useRef, useState } from "react";
import { useSession } from "@/components/auth-session";
import { useWorkspace } from "@/components/workspace-context";
import {
  dataProvider,
  dataProviderMode,
  type DailyAnalysisStatus,
} from "@/lib/data";
import { AnalyzeController, type AnalyzeState } from "./analyze-controller";
import { dailyStatusMessage } from "./daily-status-copy";

export function AnalyzeAction() {
  const session = useSession();
  const { refresh } = useWorkspace();
  const refreshRef = useRef(refresh);
  useEffect(() => { refreshRef.current = refresh; }, [refresh]);
  const [state, setState] = useState<AnalyzeState>({ busy: false, run: null, message: "", error: false });
  const [daily, setDaily] = useState<DailyAnalysisStatus | null>(null);
  const [dailyLoading, setDailyLoading] = useState(true);
  const controller = useRef<AnalyzeController | null>(null);
  useEffect(() => {
    const active = new AnalyzeController(dataProvider, setState, () => refreshRef.current());
    controller.current = active;
    return () => { active.dispose(); controller.current = null; };
  }, []);
  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    const load = async () => {
      let nextDelay = 60_000;
      try {
        const value = await dataProvider.getDailyAnalysisStatus();
        if (!live) return;
        setDaily(value);
        if (["scheduled", "refreshing", "ready", "queued", "processing"].includes(value.state)) {
          nextDelay = 15_000;
        }
      } catch {
        // Analyze remains usable if the status read is temporarily unavailable.
      } finally {
        if (live) {
          setDailyLoading(false);
          timer = window.setTimeout(() => void load(), nextDelay);
        }
      }
    };
    void load();
    return () => {
      live = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [state.run?.status]);
  const viewer = session?.workspace.role === "viewer";
  const pending = state.run && ["pending", "processing"].includes(state.run.status);
  const canResume = Boolean(daily?.runId && ["queued", "processing", "completed", "failed"].includes(daily.state));
  const dailyReserved = daily ? !daily.canRequestToday : false;
  const scheduledFor = daily?.scheduledFor
    ? `${new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: daily.timezone,
      }).format(new Date(daily.scheduledFor))} (${daily.timezone})`
    : null;
  const scheduledMessage = dailyStatusMessage(daily, scheduledFor);
  const trigger = () => {
    if (daily?.runId && canResume) {
      void controller.current?.resume(daily.runId);
      return;
    }
    void controller.current?.start();
  };
  return (
    <div className="analyze-action">
      <button
        className="button primary"
        disabled={state.busy || viewer || dailyLoading || (dailyReserved && !canResume)}
        onClick={trigger}
      >
        {state.busy
          ? "Analyzing…"
          : pending || canResume
            ? "Check today’s insight"
            : daily?.state === "failed" || daily?.state === "consumed"
              ? "Next insight tomorrow"
            : dailyReserved
              ? "Scheduled for today"
              : state.error
                ? "Retry Analyze"
                : "Analyze today"}
      </button>
      <p className={state.error ? "error-text meta" : "muted meta"} role={state.error ? "alert" : "status"}>
        {viewer
          ? "Only owners and editors can analyze context."
          : state.message || scheduledMessage || "Run one insight per workspace day using the latest saved context."}
        {dataProviderMode === "mock" && " Demo mode."}
      </p>
    </div>
  );
}
