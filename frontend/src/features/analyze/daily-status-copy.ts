import type { DailyAnalysisStatus } from "@/lib/data";

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
    return "Today’s insight is complete. The next slot opens tomorrow.";
  }
  if (daily?.state === "consumed") {
    return "Today’s insight slot was already used. Its detailed status is no longer available; the next slot opens tomorrow.";
  }
  if (daily?.state === "failed") {
    return "Today’s insight did not complete after automatic retries. Saved context is safe; the next slot opens tomorrow.";
  }
  return "";
}
