"use client";
import { useI18n } from "@/i18n/provider";
import { useEffect, useRef, useState } from "react";
import { useSession } from "@/components/auth-session";
import { useWorkspace } from "@/components/workspace-context";
import {
  dataProvider,
  dataProviderMode,
  type DailyAnalysisStatus,
} from "@/lib/data";
import { AnalyzeController, type AnalyzeState } from "./analyze-controller";
import { dailyRunChanged, dailyStatusMessage, isCurrentDailyCycle } from "./daily-status-copy";

export function AnalyzeAction() {
  const { t, locale, label, message } = useI18n();

  const session = useSession();
  const { refresh } = useWorkspace();
  const refreshRef = useRef(refresh);
  useEffect(() => { refreshRef.current = refresh; }, [refresh]);
  const [state, setState] = useState<AnalyzeState>({ busy: false, run: null, message: "", error: false });
  const [daily, setDaily] = useState<DailyAnalysisStatus | null>(null);
  const dailyRef = useRef<DailyAnalysisStatus | null>(null);
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
        if (dailyRunChanged(dailyRef.current, value)) controller.current?.reset();
        dailyRef.current = value;
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
  const currentCycle = isCurrentDailyCycle(daily);
  const dailyReserved = daily ? !daily.canRequestToday : false;
  const scheduledFor = daily?.scheduledFor
    ? `${new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: daily.timezone,
      }).format(new Date(daily.scheduledFor))} (${daily.timezone})`
    : null;
  const scheduledMessage = daily?.state === "scheduled" && daily.scheduledFor
    ? t("scheduledInsight", { date: scheduledFor ?? "" })
    : label(dailyStatusMessage(daily, scheduledFor));
  const completionMessage = state.completion ? [
    t(state.completion.today ? "Today’s insight is complete." : "Analysis complete."),
    t(state.completion.selectedChunkCount === 1
      ? "Analyzed {count} selected text section."
      : "Analyzed {count} selected text sections.", { count: state.completion.selectedChunkCount }),
    t(state.completion.hasFlares
      ? "Flares refreshed."
      : "No new Flares were found. Later additions cannot change this run’s result."),
  ].join(" ") : null;
  const trigger = () => {
    if (daily?.runId && canResume) {
      void controller.current?.resume(daily.runId, currentCycle);
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
          ? t("Analyzing…")
          : pending || canResume
            ? currentCycle ? t("Check today’s insight") : t("Check recent insight")
            : daily?.state === "failed" || daily?.state === "consumed"
              ? currentCycle ? t("Next insight tomorrow") : t("Next insight later")
            : dailyReserved
              ? t("Scheduled for today")
              : state.error
                ? t("Retry Analyze")
                : t("Analyze today")}
      </button>
      <p className={state.error ? "error-text meta" : "muted meta"} role={state.error ? "alert" : "status"}>
        {viewer
          ? t("Only owners and editors can analyze context.")
          : completionMessage ?? ((state.message ? message(state.message) : scheduledMessage) || t("Run one insight per workspace day using the latest saved context."))}
        {dataProviderMode === "mock" && <> {t("Demo mode.")}</>}
      </p>
    </div>
  );
}
