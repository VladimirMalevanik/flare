"use client";

import { useEffect, useId, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Select } from "@/components/select";
import { useI18n } from "@/i18n/provider";
import { getCampaignActivity, type CampaignActivity, type CampaignLink } from "./campaign-links-client";

const copy = {
  en: {
    activity: "Link activity", all: "All links", filter: "Filter by link", period: "Reporting period",
    days: (n: number) => `${n} days`, opens: "Recorded opens", activeDays: "Days with opens", peak: "Busiest day",
    daily: "Opens over time", comparison: "Links in this period", top: "Up to 10 links, ranked by recorded opens.",
    loading: "Loading link activity…", unavailable: "Link activity is unavailable. Your links still work.",
    refresh: "Refresh", refreshing: "Refreshing…", retry: "Try again", manage: "Create a campaign link",
    noLinks: "See how your links perform", noLinksHelp: "Create a link, share it, and recorded opens will appear here.",
    noOpens: "No opens recorded in this period.", archived: "Archived", selected: "Selected link",
    date: "Date (UTC)", dayOpens: "Opens", table: "View daily data", missing: "Not recorded",
    coverage: "Daily recording started", coverageEnd: "Earlier opens remain in lifetime totals. The first day and today may be partial.",
    timezone: "Days are shown in UTC.", keyboard: "Use the left and right arrow keys to explore days; Home and End jump to the first and last day.",
    scope: "Repeat opens and automated previews can count. These are not unique visitors or signup conversions.",
    shortLinks: "Only Flare short links (/r/…) are counted here; direct URLs with UTM tags are not included.",
    share: "of recorded opens", updated: "Updated", choose: "View activity for",
  },
  es: {
    activity: "Actividad de enlaces", all: "Todos los enlaces", filter: "Filtrar por enlace", period: "Período del informe",
    days: (n: number) => `${n} días`, opens: "Aperturas registradas", activeDays: "Días con aperturas", peak: "Día con más aperturas",
    daily: "Aperturas en el tiempo", comparison: "Enlaces en este período", top: "Hasta 10 enlaces, ordenados por aperturas registradas.",
    loading: "Cargando actividad de enlaces…", unavailable: "La actividad no está disponible. Tus enlaces siguen funcionando.",
    refresh: "Actualizar", refreshing: "Actualizando…", retry: "Reintentar", manage: "Crear un enlace de campaña",
    noLinks: "Descubre cómo funcionan tus enlaces", noLinksHelp: "Crea un enlace y compártelo. Las aperturas registradas aparecerán aquí.",
    noOpens: "No hay aperturas registradas en este período.", archived: "Archivado", selected: "Enlace seleccionado",
    date: "Fecha (UTC)", dayOpens: "Aperturas", table: "Ver datos diarios", missing: "Sin registrar",
    coverage: "El registro diario comenzó el", coverageEnd: "Las aperturas anteriores permanecen en los totales históricos. El primer día y hoy pueden estar incompletos.",
    timezone: "Los días se muestran en UTC.", keyboard: "Usa las flechas izquierda y derecha para explorar; Inicio y Fin van al primer y último día.",
    scope: "Las aperturas repetidas y las vistas previas automáticas pueden contar. No son visitantes únicos ni conversiones de registro.",
    shortLinks: "Aquí solo se cuentan los enlaces cortos de Flare (/r/…); las URL directas con etiquetas UTM no se incluyen.",
    share: "de las aperturas registradas", updated: "Actualizado", choose: "Ver actividad de",
  },
};

type Copy = (typeof copy)["en"];
type Period = CampaignActivity["days"];
const dateLabel = (value: string, locale: string, full = false) => new Intl.DateTimeFormat(locale, {
  month: "short", day: "numeric", ...(full ? { year: "numeric" as const } : {}), timeZone: "UTC",
}).format(new Date(value));

export function campaignChartPoints(daily: CampaignActivity["daily"]) {
  const max = Math.max(1, ...daily.map(day => day.opens ?? 0));
  const step = Math.max(1, Math.ceil(max / 4));
  const ceiling = step * 4;
  const points = daily.flatMap((day, index) => day.opens === null ? [] : [{
    ...day, index, x: 44 + index / Math.max(1, daily.length - 1) * 652,
    y: 200 - day.opens / ceiling * 176,
  }]);
  return { step, ceiling, points, path: points.map((point, index) => `${index ? "L" : "M"}${point.x},${point.y}`).join(" ") };
}

export function CampaignActivityPanel({ links, loading, failed, onRetryLinks, onManage }: {
  links: CampaignLink[]; loading: boolean; failed: boolean; onRetryLinks: () => void; onManage: () => void;
}) {
  const { locale } = useI18n();
  const c = copy[locale];
  const [days, setDays] = useState<Period>(30);
  const [selected, setSelected] = useState<{ id: string; label: string } | null>(null);
  const [revision, setRevision] = useState(0);
  const linksRevision = links.map(link => `${link.id}:${link.archivedAt ?? ""}:${link.clickCount}`).join("|");
  const options = [{ value: "", label: c.all }, ...links.map(link => ({
    value: link.id, label: `${link.label}${link.archivedAt ? ` · ${c.archived}` : ""}`,
  }))];
  if (selected && !links.some(link => link.id === selected.id)) options.push({ value: selected.id, label: selected.label });
  if (loading) return <p className="campaign-activity-state muted" role="status">{c.loading}</p>;
  if (failed) return <div className="campaign-activity-state"><p role="alert">{c.unavailable}</p><button type="button" className="button" onClick={onRetryLinks}>{c.retry}</button></div>;
  if (!links.length) return <div className="campaign-activity-state campaign-activity-empty">
    <h3>{c.noLinks}</h3><p className="muted">{c.noLinksHelp}</p>
    <button type="button" className="button primary" onClick={onManage}>{c.manage}</button>
  </div>;
  return <div className="campaign-activity">
    <div className="campaign-activity-controls">
      <Select value={selected?.id ?? ""} options={options} aria-label={c.filter}
        onValueChange={id => setSelected(id ? { id, label: links.find(link => link.id === id)?.label ?? c.selected } : null)} />
      <div className="campaign-periods" role="group" aria-label={c.period}>
        {([7, 30, 90] as const).map(period => <button type="button" key={period} aria-pressed={days === period}
          onClick={() => setDays(period)}>{c.days(period)}</button>)}
      </div>
      <button type="button" className="button" onClick={() => { setRevision(value => value + 1); onRetryLinks(); }}>{c.refresh}</button>
    </div>
    <CampaignActivityResult key={`${days}:${selected?.id ?? "all"}:${revision}:${linksRevision}`}
      days={days} linkId={selected?.id ?? null} c={c} locale={locale}
      onRetry={() => setRevision(value => value + 1)} onSelect={setSelected} />
  </div>;
}

export function CampaignActivityResult({ days, linkId, c, locale, onRetry, onSelect }: {
  days: Period; linkId: string | null; c: Copy; locale: string; onRetry: () => void;
  onSelect: (link: { id: string; label: string }) => void;
}) {
  const [result, setResult] = useState<CampaignActivity | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    void getCampaignActivity(days, linkId, controller.signal)
      .then(data => { if (live) setResult(data); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; controller.abort(); };
  }, [days, linkId]);
  if (failed) return <div className="campaign-activity-state"><p role="alert">{c.unavailable}</p>
    <button type="button" className="button" onClick={onRetry}>{c.retry}</button></div>;
  if (!result) return <p className="campaign-activity-state muted" role="status">{c.loading}</p>;
  const activeDays = result.daily.filter(day => (day.opens ?? 0) > 0).length;
  const peak = result.daily.reduce<(typeof result.daily)[number] | null>((best, day) =>
    day.opens !== null && day.opens > (best?.opens ?? 0) ? day : best, null);
  const largest = Math.max(1, ...result.topLinks.map(link => link.opens));
  return <div className="campaign-activity-results">
    <dl className="campaign-activity-metrics">
      <div><dt>{c.opens}</dt><dd>{result.totalOpens.toLocaleString(locale)}</dd></div>
      <div><dt>{c.activeDays}</dt><dd>{activeDays.toLocaleString(locale)}</dd></div>
      <div><dt>{c.peak}</dt><dd className="campaign-peak">{peak ? dateLabel(peak.date, locale) : "—"}
        {peak && <span>{peak.opens?.toLocaleString(locale)} {c.dayOpens.toLowerCase()}</span>}</dd></div>
    </dl>
    <DailyOpensChart result={result} c={c} locale={locale} />
    {result.recordingStartedAt && <p className="campaign-coverage muted meta">
      {c.coverage} <time dateTime={result.recordingStartedAt}>{dateLabel(result.recordingStartedAt, locale, true)}</time>. {c.coverageEnd}
    </p>}
    <section className="campaign-breakdown" aria-label={c.comparison}>
      <div className="campaign-breakdown-heading"><h3>{c.comparison}</h3><p className="muted meta">{c.top}</p></div>
      <ul>{result.topLinks.map(link => <li key={link.id}>
        <button type="button" className="campaign-ranking" onClick={() => onSelect({ id: link.id, label: link.label })}
          aria-label={`${c.choose} ${link.label}, ${link.opens.toLocaleString(locale)} ${c.dayOpens.toLowerCase()}`}>
          <span className="campaign-ranking-name">{link.label}{link.archivedAt && <span className="badge">{c.archived}</span>}</span>
          <span className="campaign-ranking-count">{link.opens.toLocaleString(locale)}
            <span>{new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 1 }).format(result.totalOpens ? link.opens / result.totalOpens : 0)}</span>
          </span>
          <span className="campaign-ranking-track" aria-hidden="true"><span style={{ width: `${link.opens / largest * 100}%` }} /></span>
        </button>
      </li>)}</ul>
    </section>
    <p className="muted meta campaign-activity-footnote">{c.scope} {c.shortLinks} {c.timezone}<br />
      {c.updated} <time dateTime={result.generatedAt}>{new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit", timeZone: "UTC" }).format(new Date(result.generatedAt))} {result.timezone}</time>.
    </p>
  </div>;
}

function DailyOpensChart({ result, c, locale }: { result: CampaignActivity; c: Copy; locale: string }) {
  const id = useId();
  const { points, path, step } = campaignChartPoints(result.daily);
  const [active, setActive] = useState<number | null>(null);
  const selected = active === null ? null : points.find(point => point.index === active);
  function keyDown(event: KeyboardEvent<SVGSVGElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || !points.length) return;
    event.preventDefault();
    const current = points.findIndex(point => point.index === active);
    const next = event.key === "Home" ? 0 : event.key === "End" ? points.length - 1 :
      Math.max(0, Math.min(points.length - 1, (current < 0 ? 0 : current) + (event.key === "ArrowRight" ? 1 : -1)));
    setActive(points[next].index);
  }
  function pointAt(event: MouseEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - bounds.left) / bounds.width * 720;
    const index = Math.round((x - 44) / 652 * Math.max(1, result.daily.length - 1));
    setActive(Math.max(points[0]?.index ?? 0, Math.min(result.daily.length - 1, index)));
  }
  const ticks = [...new Set([0, Math.floor((result.daily.length - 1) / 2), result.daily.length - 1])];
  return <figure className="campaign-chart">
    <figcaption><h3>{c.daily}</h3><span className="campaign-chart-value" aria-live="polite">
      {selected ? `${dateLabel(selected.date, locale)} · ${selected.opens?.toLocaleString(locale)} ${c.dayOpens.toLowerCase()}` :
        `${dateLabel(result.daily[0].date, locale)} – ${dateLabel(result.daily.at(-1)!.date, locale)}`}
    </span></figcaption>
    <svg viewBox="0 0 720 240" role="group" tabIndex={0} aria-labelledby={`${id}-title`} aria-describedby={`${id}-help`}
      onKeyDown={keyDown} onMouseMove={pointAt} onMouseLeave={() => setActive(null)}
      onFocus={() => setActive(points.at(-1)?.index ?? null)} onBlur={() => setActive(null)}>
      <title id={`${id}-title`}>{c.daily} · {result.totalOpens.toLocaleString(locale)} {c.opens.toLowerCase()}</title>
      <desc id={`${id}-help`}>{c.keyboard} {c.timezone}</desc>
      {[0, 1, 2, 3, 4].map(index => <g key={index} className="campaign-chart-grid" aria-hidden="true">
        <line x1="44" x2="696" y1={200 - index * 44} y2={200 - index * 44} />
        <text x="32" y={204 - index * 44} textAnchor="end">{(index * step).toLocaleString(locale)}</text>
      </g>)}
      {points.length > 0 && <>
        <path d={`${path} L${points.at(-1)!.x},200 L${points[0].x},200 Z`} className="campaign-chart-area" />
        <path d={path} className="campaign-chart-line" />
        {points.length === 1 && <circle cx={points[0].x} cy={points[0].y} r="4" className="campaign-chart-dot" />}
      </>}
      {selected && <g aria-hidden="true"><line className="campaign-chart-cursor" x1={selected.x} x2={selected.x} y1="24" y2="200" />
        <circle cx={selected.x} cy={selected.y} r="5" className="campaign-chart-dot" /></g>}
      {ticks.map(index => <text key={index} className="campaign-chart-date" x={44 + index / (result.daily.length - 1) * 652} y="228"
        textAnchor={index === 0 ? "start" : index === result.daily.length - 1 ? "end" : "middle"} aria-hidden="true">{dateLabel(result.daily[index].date, locale)}</text>)}
    </svg>
    {!result.totalOpens && <p className="muted meta campaign-chart-zero">{c.noOpens}</p>}
    <details className="campaign-chart-data"><summary>{c.table}</summary>
      <div><table><caption className="sr-only">{c.daily}</caption><thead><tr><th scope="col">{c.date}</th><th scope="col">{c.dayOpens}</th></tr></thead>
        <tbody>{result.daily.map(day => <tr key={day.date}><th scope="row"><time dateTime={day.date}>{dateLabel(day.date, locale, true)}</time></th>
          <td>{day.opens === null ? c.missing : day.opens.toLocaleString(locale)}</td></tr>)}</tbody></table></div>
    </details>
  </figure>;
}
