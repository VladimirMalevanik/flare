import { Suspense } from "react";
import { InsightsPage } from "@/features/insights/insights-page";
export default function Insights() { return <Suspense fallback={<div className="p-6">Loading Flares…</div>}><InsightsPage /></Suspense>; }
