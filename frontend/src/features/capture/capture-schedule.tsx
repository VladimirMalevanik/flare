"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { useI18n } from "@/i18n/provider";
import { dataProvider, type AnalysisSchedule } from "@/lib/data";
import { importRequest } from "@/lib/data/import-request";
import { projectHref } from "@/lib/team-context";

export const CAPTURE_SCHEDULE_TIMEOUT_MS = 4000;
export const CAPTURE_TOAST_DISMISS_MS = 8000;

export function CaptureConfirmation({ itemId, onDismiss }: { itemId: string; onDismiss: () => void }) {
  const { t } = useI18n();
  const timer = useRef<number | null>(null);
  const hovered = useRef(false);
  const pause = useCallback(() => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  }, []);
  const resume = useCallback(() => {
    pause();
    if (!hovered.current) timer.current = window.setTimeout(onDismiss, CAPTURE_TOAST_DISMISS_MS);
  }, [onDismiss, pause]);
  useEffect(() => { resume(); return pause; }, [resume, pause]);

  return <div className="toast capture-toast" role="status" aria-live="polite"
    onMouseEnter={() => { hovered.current = true; pause(); }}
    onMouseLeave={event => {
      hovered.current = false;
      if (!event.currentTarget.contains(document.activeElement)) resume();
    }}
    onFocusCapture={pause}
    onBlurCapture={event => {
      if (!event.currentTarget.contains(event.relatedTarget)) resume();
    }}>
    <div className="capture-toast-copy">
      <strong>{t("Captured in Vault")}</strong>
      <CaptureSchedule onNavigate={onDismiss} />
      <Link href={projectHref(`/vault?item=${encodeURIComponent(itemId)}`)} onClick={onDismiss}>{t("View item →")}</Link>
    </div>
    <button className="icon-button" aria-label={t("Dismiss capture confirmation")} onClick={onDismiss}>
      <Icon name="close" />
    </button>
  </div>;
}

/** A read-only next step; saving context never enables or starts analysis. */
export function CaptureSchedule({ onNavigate }: { onNavigate: () => void }) {
  const { t, locale } = useI18n();
  const [result, setResult] = useState<(AnalysisSchedule & { checkedAt: number }) | "unavailable" | null>(null);

  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    void importRequest(
      signal => dataProvider.getAnalysisSchedule(signal),
      controller.signal,
      CAPTURE_SCHEDULE_TIMEOUT_MS,
    ).then(value => {
      if (live) setResult({ ...value, checkedAt: Date.now() });
    }).catch(() => {
      if (live) setResult("unavailable");
    });
    return () => { live = false; controller.abort(); };
  }, []);

  let copy = t("Checking insight schedule…");
  let needsSchedule = false;
  const preparation = result && result !== "unavailable" && result.nextRefreshAt
    ? Date.parse(result.nextRefreshAt) : NaN;
  const checkedAt = result && result !== "unavailable" ? result.checkedAt : NaN;
  const preparationMayBeComplete = Number.isFinite(preparation) && preparation <= checkedAt;
  if (result === "unavailable") {
    copy = t("Your content is saved. The insight time is unavailable.");
  } else if (result) {
    needsSchedule = !result.enabled;
    if (needsSchedule) {
      copy = t("Scheduled insights are off. Set a time to analyze your saved notes.");
    } else {
      copy = t("Your schedule is on. Check its next run in Settings.");
      if (result.nextRunAt) {
        try {
          const date = new Intl.DateTimeFormat(locale, {
            dateStyle: "medium", timeStyle: "short", timeZone: result.timezone,
          }).format(new Date(result.nextRunAt));
          copy = t("Next scheduled insight: {date}", { date: `${date} (${result.timezone})` });
        } catch {
          copy = t("Your content is saved. The insight time is unavailable.");
        }
      }
    }
  }

  return <>
    <small className="capture-schedule-copy">{copy}</small>
    {result && result !== "unavailable" && result.enabled && preparationMayBeComplete &&
      <small className="capture-schedule-copy">{t("Notes added after preparation may wait for the following scheduled run.")}</small>}
    <Link className="text-button capture-schedule-link" href={projectHref("/settings#daily-insight")} onClick={onNavigate}>
      {needsSchedule ? t("Set insight time") : t("Analysis schedule")}
    </Link>
  </>;
}
