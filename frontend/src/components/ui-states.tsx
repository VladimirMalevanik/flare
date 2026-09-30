"use client";
import { useI18n } from "@/i18n/provider";
export function LoadingState({ label }: { label?: string }) { const { t, label: translate } = useI18n(); return <div className="animate-pulse p-6 text-sm text-slate-500">{label ? translate(label) : t("loading")}</div>; }
export function EmptyState({ title, detail }: { title: string; detail: string }) { const { label } = useI18n(); return <div className="p-8 text-center"><p className="font-medium">{label(title)}</p><p className="mt-1 text-slate-500">{label(detail)}</p></div>; }
export function ErrorState({ message }: { message: string }) { const { message: translate } = useI18n(); return <div role="alert" className="m-4 rounded-md border border-red-200 bg-red-50 p-3 text-red-800">{translate(message)}</div>; }
