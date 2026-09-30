"use client";
import { useI18n } from "@/i18n/provider";
export default function AppError({ reset }: { reset: () => void }) {
  const { t } = useI18n();

  return <main className="auth-page"><section className="auth-panel"><h1>{t("Unable to open your workspace")}</h1><p>{t("Please check your connection and try again.")}</p><button className="button primary" onClick={reset}>{t("Try again")}</button></section></main>;
}
