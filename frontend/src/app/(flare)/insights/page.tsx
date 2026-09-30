"use client";
import { useI18n } from "@/i18n/provider";
import { Suspense } from "react";
import { InsightsPage } from "@/features/insights/insights-page";
export default function Insights() {
  const { t } = useI18n();
 return <Suspense fallback={<div className="p-6">{t("Loading Flares…")}</div>}><InsightsPage /></Suspense>; }
