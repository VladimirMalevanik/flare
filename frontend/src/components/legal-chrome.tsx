"use client";
import Link from "next/link";
import { useI18n } from "@/i18n/provider";

export function LegalChrome({ kind }: { kind: "start" | "footer" }) {
  const { t } = useI18n();
  if (kind === "start") return <Link className="button" href="/register">{t("getStarted")}</Link>;
  return <>
    <Link href="/privacy">{t("privacyPolicy")}</Link>
    <Link href="/terms">{t("termsOfService")}</Link>
    <Link href="/">{t("backToFlare")}</Link>
  </>;
}
