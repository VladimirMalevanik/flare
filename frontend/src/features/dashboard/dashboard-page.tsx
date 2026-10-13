"use client";
import { useI18n } from "@/i18n/provider";
import { relativeTime } from "@/i18n/translate";
import type { Locale } from "@/i18n/config";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { dataErrorMessage, dataProvider, dataProviderMode, type Item, type ItemStatus, type ItemType as DataItemType } from "@/lib/data";
import { ErrorState, LoadingState } from "@/components/ui-states";
import { Icon, itemIcon } from "@/components/icons";
import { ItemType } from "@/components/item-type";
import { useWorkspace } from "@/components/workspace-context";

const captureModes: { type: DataItemType; label: string }[] = [{ type:"note", label:"Write note" }, { type:"url", label:"Paste URL" }, { type:"file", label:"Upload file" }, { type:"audio", label:"Voice coming soon" }];
const shortTime = (date: string, locale: Locale) => relativeTime(locale, date);
export function DashboardPage() {
  const { t, locale, label } = useI18n();

  const { openCapture } = useWorkspace();
  const [items, setItems] = useState<Item[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [mode, setMode] = useState<DataItemType>("note"); const [value, setValue] = useState(""); const [status, setStatus] = useState<ItemStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const capturePending = useRef(false);
  const draft = useRef({ mode: "note" as DataItemType, value: "", revision: 0 });
  const statusTimer = useRef<number | undefined>(undefined);
  const mounted = useRef(true);
  const loadGeneration = useRef(0);
  const editDraft = (nextMode: DataItemType, nextValue: string) => {
    draft.current = { mode: nextMode, value: nextValue, revision: draft.current.revision + 1 };
    setMode(nextMode); setValue(nextValue);
  };
  const load = async () => {
    const generation = ++loadGeneration.current;
    setItemsError(null);
    try {
      const recent = await dataProvider.listItems({ limit: 5 });
      if (mounted.current && generation === loadGeneration.current) setItems(recent);
    } catch (caught) {
      if (mounted.current && generation === loadGeneration.current) setItemsError(dataErrorMessage(caught, "Your recent items could not be loaded."));
    } finally {
      if (mounted.current && generation === loadGeneration.current) setLoading(false);
    }
  };
  useEffect(() => {
    mounted.current = true;
    const timer = window.setTimeout(() => { void load(); }, 0);
    return () => { mounted.current = false; window.clearTimeout(timer); window.clearTimeout(statusTimer.current); };
  }, []);
  const capture = async () => {
    if (capturePending.current || !draft.current.value.trim()) return;
    capturePending.current = true; setSaving(true); setError(null);
    const submitted = draft.current;
    const payload = submitted.mode === "url"
      ? { type: "url" as const, sourceUrl: submitted.value, content: submitted.value }
      : { type: "note" as const, content: submitted.value };
    // Telemetry should never prevent the save or turn a successful save into an error.
    const track = (event: Parameters<typeof dataProvider.trackEvent>[0]) => {
      try { void dataProvider.trackEvent(event).catch(() => {}); } catch { /* Optional telemetry. */ }
    };
    track({ eventType:"capture_started", targetType: "capture" });
    try {
      const next = await dataProvider.createItem(payload);
      track({ eventType:"capture_submitted", targetType: "item", targetId: next.id, metadata: { sourceType: payload.type } });
      if (!mounted.current) return;
      // Confirm the saved item before independently refreshing the recent list.
      ++loadGeneration.current;
      setLoading(false);
      setItems((current) => [next, ...current.filter((item) => item.id !== next.id)].slice(0, 5));
      if (draft.current.revision === submitted.revision) editDraft(submitted.mode, "");
      setStatus(next.status);
      window.clearTimeout(statusTimer.current);
      statusTimer.current = window.setTimeout(() => setStatus(null), 2400);
      void load();
    } catch (caught) {
      if (mounted.current) setError(dataErrorMessage(caught, "Capture failed. Try again."));
    } finally {
      capturePending.current = false;
      if (mounted.current) setSaving(false);
    }
  };
  const ready = Boolean(value.trim());
  return <div className="mx-auto max-w-4xl space-y-8 px-4 py-8 sm:px-8 sm:py-10"><section className="border-b hairline pb-4"><h1 className="text-[24px] font-semibold tracking-[-.03em]">{t("Good morning, Alex")}</h1><p className="mt-1 text-slate-500">{t("Your project memory and recent Flares.")}</p></section>
  <section className="overflow-hidden rounded-xl border hairline bg-white"><div className="flex overflow-x-auto border-b hairline px-3 pt-3"><div className="flex gap-1">{captureModes.map((entry) => <button key={entry.type} disabled={entry.type === "audio"} onClick={() => { if (entry.type === "file") { openCapture(); return; } editDraft(entry.type, ""); }} className={`focus-ring inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] disabled:cursor-not-allowed disabled:opacity-45 ${mode === entry.type ? "border hairline bg-slate-50 font-medium" : "text-slate-500 hover:bg-slate-50 hover:text-slate-950"}`}><Icon name={itemIcon[entry.type]} className="h-4 w-4"/>{label(entry.label)}</button>)}</div></div>
  <div className="p-3"><textarea value={value} aria-label={t("Capture content")} onChange={(event) => editDraft(draft.current.mode, event.target.value)} onKeyDown={(event) => { if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && ready) { event.preventDefault(); void capture(); } }} rows={3} className="focus-ring w-full resize-none rounded p-1 text-[15px] leading-relaxed outline-none" placeholder={mode === "url" ? t("Paste a URL to keep it close…") : t("Drop thoughts, meeting notes, decisions, paste links, or press ⌘Enter…")}/></div>
  <div className="flex items-center justify-between border-t hairline bg-slate-50/70 px-3 py-2.5"><span className="mono text-[10px] text-slate-500">{status === "processing" ? t("Saved · processing") : dataProviderMode === "api" ? t("Stored in PostgreSQL") : t("Stored locally in this MVP")}</span><button disabled={!ready || saving} onClick={() => void capture()} className="focus-ring rounded-md bg-slate-950 px-4 py-1.5 text-[13px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-35">{saving ? t("Saving…") : t("Capture")}</button></div></section>
  {error && <ErrorState message={error}/>}<div className="grid items-start gap-8 lg:grid-cols-12"><section className="space-y-3 lg:col-span-7"><div className="flex items-center justify-between"><h2 className="font-semibold">{t("Recently Added")}</h2><Link className="text-xs text-slate-500 hover:text-slate-950" href="/vault">{t("View all")}</Link></div>{itemsError && <div><ErrorState message={itemsError}/><button className="focus-ring text-xs text-slate-600 underline" onClick={() => void load()}>{t("Try again")}</button></div>}<div className="overflow-hidden rounded-xl border hairline bg-white divide-y divide-slate-100">{loading ? <LoadingState/> : items.map((item) => <Link href={`/vault?item=${item.id}`} key={item.id} className="flex items-center justify-between gap-3 p-3.5 hover:bg-slate-50"><span className="flex min-w-0 items-center gap-2.5"><Icon name={itemIcon[item.type]} className="h-[17px] w-[17px] shrink-0 text-slate-500"/><span className="truncate font-medium">{item.title}</span></span><span className="flex shrink-0 items-center gap-2"><span className="hidden sm:block"><ItemType type={item.type}/></span>{item.status === "processing" && <span className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">{t("Processing…")}</span>}<time className="text-xs text-slate-500">{shortTime(item.createdAt, locale)}</time></span></Link>)}</div></section>
  <RecentInsights/></div></div>;
}
function RecentInsights() {
  const { t, locale } = useI18n();
  const [insights, setInsights] = useState<Awaited<ReturnType<typeof dataProvider.listInsights>>>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const request = useRef(0);
  const load = async () => {
    const generation = ++request.current;
    setLoading(true); setError(null);
    try {
      const recent = await dataProvider.listInsights();
      if (generation === request.current) setInsights(recent);
    } catch (caught) {
      if (generation === request.current) setError(dataErrorMessage(caught, "Recent Flares could not be loaded. Try again."));
    } finally {
      if (generation === request.current) setLoading(false);
    }
  };
  useEffect(() => {
    const activeRequest = request;
    const timer = window.setTimeout(() => void load(), 0);
    return () => { ++activeRequest.current; window.clearTimeout(timer); };
  }, []);
  return <section className="space-y-3 lg:col-span-5"><h2 className="font-semibold">{t("Recent Flares")}</h2>
    {error && <div><ErrorState message={error}/><button disabled={loading} className="focus-ring text-xs text-slate-600 underline" onClick={() => void load()}>{t("Try again")}</button></div>}
    <div className="space-y-3">{loading ? <LoadingState/> : insights.slice(0,2).map((insight) => <Link key={insight.id} href={`/insights?insight=${insight.id}`} className="block space-y-2.5 rounded-xl border hairline bg-white p-4 hover:border-slate-300"><h3 className="font-semibold leading-snug">{insight.title}</h3><p className="leading-relaxed text-slate-500">{insight.statement}</p><div className="flex justify-between border-t hairline pt-2 text-xs text-slate-500"><span>{t("Updated")}{" "}{shortTime(insight.createdAt, locale)}</span><span className="font-medium text-slate-950">{insight.evidence.length} {" "}{t("pieces of evidence →")}</span></div></Link>)}</div></section>;
}
