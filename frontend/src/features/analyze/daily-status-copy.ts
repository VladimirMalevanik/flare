import type { DailyAnalysisStatus } from "@/lib/data";

export function dailyRunChanged(
  previous: DailyAnalysisStatus | null,
  current: DailyAnalysisStatus,
): boolean {
  return Boolean(previous && (
    previous.localDate !== current.localDate
    || (previous.runId && previous.runId !== current.runId)
  ));
}

export function isCurrentDailyCycle(daily: DailyAnalysisStatus | null): boolean {
  if (!daily?.scheduledFor) return true;
  const parts = new Intl.DateTimeFormat("en-US", {
    year: "numeric", month: "2-digit", day: "2-digit", timeZone: daily.timezone,
  }).formatToParts(new Date(daily.scheduledFor));
  const part = (type: string) => parts.find(value => value.type === type)?.value;
  return `${part("year")}-${part("month")}-${part("day")}` === daily.localDate;
}

export function dailyStatusMessage(
  daily: DailyAnalysisStatus | null,
  scheduledFor: string | null,
): string {
  if (daily?.state === "scheduled" && daily.scheduledFor) {
    return `Next insight is scheduled for ${scheduledFor}. Saved source versions are prepared 30 minutes earlier.`;
  }
  if (daily?.state === "refreshing") {
    return "Flare is preparing the latest saved context for today’s insight.";
  }
  if (daily?.state === "ready") {
    return "Fresh context is ready. Today’s insight will start at the scheduled time.";
  }
  if (daily?.state === "completed") {
    if (!isCurrentDailyCycle(daily)) return "The most recent insight is complete. The next analysis slot is not available yet.";
    return "Today’s insight is complete. The next slot opens tomorrow.";
  }
  if (daily?.state === "consumed") {
    if (!isCurrentDailyCycle(daily)) return "The previous insight slot was used. The next analysis slot is not available yet.";
    return "Today’s insight slot was already used. Its detailed status is no longer available; the next slot opens tomorrow.";
  }
  if (daily?.state === "failed") {
    if (!isCurrentDailyCycle(daily)) return "The most recent insight did not complete. The next analysis slot is not available yet.";
    return "Today’s insight did not complete after automatic retries. Saved context is safe; the next slot opens tomorrow.";
  }
  return "";
}
