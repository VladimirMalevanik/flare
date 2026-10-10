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
import { withRequestDeadline } from "./request-deadline";
import { dailyRunChanged, dailyStatusMessage, isCurrentDailyCycle } from "./daily-status-copy";
import { consumeFunnyRequest, funnyMessage, REQUIRED_SHAKES } from "@/features/funny/funny-state";
import { playFunnySound, speakFunnyLine } from "@/features/funny/funny-sounds";

export function AnalyzeAction() {
  const { t, locale, label, message } = useI18n();

  const session = useSession();
  const { refresh, captureOpen, funnyMode, funnySounds, funnyAudioPaused, funnyRitual, setFunnyRitual } = useWorkspace();
  const consumedGesture = useRef(0);
  const feedbackFor = useRef(0);
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
    return () => {
      active.dispose(); controller.current = null;
      setFunnyRitual((value) => ({ ...value, phase: "idle", shakes: 0 }));
    };
  }, [setFunnyRitual]);
  useEffect(() => {
    let live = true;
    let timer: number | undefined;
    let request: AbortController | undefined;
    const load = async () => {
      let nextDelay = 60_000;
      request = new AbortController();
      try {
        const value = await withRequestDeadline(() => dataProvider.getDailyAnalysisStatus(request?.signal), request);
        if (!live) return;
        if (dailyRunChanged(dailyRef.current, value)) {
          controller.current?.reset();
          setFunnyRitual((ritual) => ({ ...ritual, phase: "idle", shakes: 0 }));
        }
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
      request?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [state.run?.status, setFunnyRitual]);
  const viewer = session?.workspace.role === "viewer";
  const pending = state.run && ["pending", "processing"].includes(state.run.status);
  const canResume = Boolean(daily?.runId && ["queued", "processing", "completed", "failed"].includes(daily.state));
  const currentCycle = isCurrentDailyCycle(daily);
  const dailyReserved = daily ? !daily.canRequestToday : false;
  const disabled = state.busy || viewer || dailyLoading || (dailyReserved && !canResume);
  const gestureEligible = !disabled && !dailyReserved && !canResume;
  useEffect(() => {
    if (!funnyMode || captureOpen || !gestureEligible) {
      setFunnyRitual((value) => value.phase === "armed" || value.phase === "shaken"
        ? { ...value, phase: "idle", shakes: 0 } : value);
      return;
    }
    const requestId = consumeFunnyRequest(funnyRitual, consumedGesture.current, Boolean(controller.current));
    if (requestId === null) return;
    consumedGesture.current = requestId;
    setFunnyRitual((value) => ({ ...value, phase: "thinking" }));
    // The existing controller owns idempotency, real progress, errors and quota.
    void controller.current?.start();
  }, [funnyMode, captureOpen, gestureEligible, funnyRitual, setFunnyRitual]);
  useEffect(() => {
    if (funnyRitual.phase !== "thinking" || state.busy || (!state.completion && !state.error)) return;
    const phase = state.error ? "error" : state.completion?.hasFlares ? "complete" : "empty";
    setFunnyRitual((value) => ({ ...value, phase }));
    if (feedbackFor.current !== funnyRitual.requestId) {
      feedbackFor.current = funnyRitual.requestId;
      playFunnySound(phase === "complete" ? "success" : phase, funnyMode && funnySounds && !funnyAudioPaused);
    }
  }, [state, funnyRitual, setFunnyRitual, funnyMode, funnySounds, funnyAudioPaused]);
  useEffect(() => {
    if (funnyRitual.phase !== "armed") return;
    const cancel = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFunnyRitual((value) => ({ ...value, phase: "idle", shakes: 0 }));
    };
    window.addEventListener("keydown", cancel);
    return () => window.removeEventListener("keydown", cancel);
  }, [funnyRitual.phase, setFunnyRitual]);
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
    if (disabled) return;
    if (daily?.runId && canResume) {
      if (funnyMode) {
        setFunnyRitual((value) => ({ phase: "thinking", requestId: value.requestId + 1, shakes: 0 }));
        playFunnySound("click", funnySounds && !funnyAudioPaused);
      }
      void controller.current?.resume(daily.runId, currentCycle);
      return;
    }
    if (funnyMode) {
      if (funnyRitual.phase !== "armed") {
        setFunnyRitual((value) => ({ phase: "armed", requestId: value.requestId + 1, shakes: 0 }));
        speakFunnyLine("Nah, dude. Shake the ball.", funnySounds && !funnyAudioPaused);
      }
      document.querySelector<HTMLButtonElement>(".flare-capture-trigger")?.focus({ preventScroll: true });
      return;
    }
    void controller.current?.start();
  };
  return (
    <div className="analyze-action">
      <button
        className="button primary"
        disabled={disabled || funnyRitual.phase === "shaken"}
        data-funny-sound={funnyMode ? "off" : undefined}
        onClick={trigger}
      >
        {funnyMode && funnyRitual.phase === "armed" ? t("Shake the 8-ball") : state.busy
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
      {funnyMode && funnyRitual.phase !== "idle" && <div className="funny-ritual-panel">
        <span className="funny-ritual-kicker">{t("MAGIC 8-BALL · REAL EVIDENCE")}</span>
        <p className="funny-ritual-message">{funnyMessage(funnyRitual)}</p>
        {funnyRitual.phase === "armed" && <>
          <small>{t("Shake progress", { count: Math.min(funnyRitual.shakes, REQUIRED_SHAKES), total: REQUIRED_SHAKES })}</small>
          <button className="text-button" onClick={() => setFunnyRitual((value) => ({ ...value, phase: "idle", shakes: 0 }))}>{t("Cancel · Esc")}</button>
        </>}
      </div>}
      <p className={state.error ? "error-text meta" : "muted meta"} role={state.error ? "alert" : "status"}>
        {viewer
          ? t("Only owners and editors can analyze context.")
          : completionMessage ?? ((state.message ? message(state.message) : scheduledMessage) || t("Run one insight per workspace day using the latest saved context."))}
        {dataProviderMode === "mock" && <> {t("Demo mode.")}</>}
      </p>
    </div>
  );
}
