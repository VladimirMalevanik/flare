"use client";
import { useI18n } from "@/i18n/provider";
import Link from "next/link";
import { AnalyzeAction } from "@/features/analyze/analyze-action";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  dataProvider,
  type Insight,
} from "@/lib/data";
import { Icon } from "@/components/icons";
import { useWorkspace } from "@/components/workspace-context";
import { nextFlareViewEvent, resetFlareView } from "./view-analytics";
const flareTypes = ["Reminder", "Warning", "Recommendation"] as const;
type FlareType = (typeof flareTypes)[number];
const plural: Record<FlareType, string> = {
  Reminder: "Reminders", Warning: "Warnings", Recommendation: "Recommendations",
};
const flareTypeFor = (insight: Insight): FlareType => insight.type;
export function InsightsPage() {
  const { t, locale, label, message } = useI18n();

  const params = useSearchParams();
  const detailId = params.get("insight");
  const [insights, setInsights] = useState<Insight[]>([]);
  const [selected, setSelected] = useState<Insight | null>(null);
  const [detail, setDetail] = useState<{ id: string; value: Insight | null; error: string } | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [itemCount, setItemCount] = useState(0);
  const [filter, setFilter] = useState<FlareType | "All">("All");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const viewedFlare = useRef<string | null>(null);
  const recordFlareView = useCallback((flareId: string) => {
    const event = nextFlareViewEvent(viewedFlare, flareId, crypto.randomUUID());
    if (event) void dataProvider.trackEvent(event);
  }, []);
  const closePanel = useCallback(() => {
    resetFlareView(viewedFlare);
    setPanelOpen(false);
  }, []);
  const { openCapture, revision } = useWorkspace();
  useEffect(() => {
    let live = true;
    void Promise.all([dataProvider.listInsights(), dataProvider.listItems()])
      .then(([list, items]) => {
        if (live) {
          setError("");
          setInsights(list);
          setItemCount(items.length);
        }
      })
      .catch(() => {
        if (live)
          setError("Flares could not be loaded. Refresh to try again.");
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [revision]);
  useEffect(() => {
    if (!detailId) return;
    let live = true;
    void dataProvider.getInsight(detailId)
      .then((value) => {
        if (live) {
          setDetail({ id: detailId, value, error: "" });
          setPanelOpen(true);
        }
      })
      .catch(() => {
        if (live) {
          setDetail({ id: detailId, value: null, error: "Flare could not be loaded. Refresh to try again." });
          setPanelOpen(true);
        }
      });
    return () => { live = false; };
  }, [detailId, recordFlareView, revision]);
  const visible = insights.filter(
    (insight) => filter === "All" || flareTypeFor(insight) === filter,
  );
  const urlDetail = detail?.id === detailId ? detail : null;
  const active = panelOpen ? (detailId ? urlDetail?.value : selected) : null;
  useEffect(() => {
    if (!panelOpen) return;
    const outside = (event: PointerEvent) => {
      if (
        event.target instanceof Element &&
        !event.target.closest(".evidence-panel, .insight-card, .filters")
      ) {
        closePanel();
      }
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closePanel();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [closePanel, panelOpen]);
  const toggleInsight = (id: string) => {
    const opening = !panelOpen || active?.id !== id;
    setSelected(insights.find((insight) => insight.id === id) ?? null);
    if (!opening) {
      closePanel();
      return;
    }
    setPanelOpen(true);
    if (opening && detailId !== id) {
      const url = new URL(window.location.href);
      url.searchParams.set("insight", id);
      window.history.pushState(null, "", url);
    }
    if (window.innerWidth <= 1050)
      requestAnimationFrame(() =>
        document
          .querySelector(".evidence-panel")
          ?.scrollIntoView({ block: "start" }),
      );
    recordFlareView(id);
  };
  return (
    <div className={`insights-layout ${active ? "with-evidence" : ""}`}>
      <section className="page insight-feed">
        <div className="insights-header">
          <header className="page-heading">
            <p className="eyebrow">
              <span className="dot" />
              {" "}{t("RECENT FLARES ·")}{" "}{insights.length} {" "}{t("SURFACED")}</p>
            <h1>Flares</h1>
            <p>{t("Things you might have missed, forgotten, or contradicted.")}</p>
          </header>
          <AnalyzeAction />
        </div>
        <div className="filters">
          <button
            className={`filter ${filter === "All" ? "selected" : ""}`}
            onClick={() => {
              setFilter("All");
            }}
          >
            {t("All")}{" "}<span>{insights.length}</span>
          </button>
          {flareTypes.map((kind) => (
            <button
              key={kind}
              className={`filter ${filter === kind ? "selected" : ""}`}
              onClick={() => {
                setFilter(kind);
              }}
            >
              {label(plural[kind])}{" "}
              <span>
                {insights.filter((insight) => flareTypeFor(insight) === kind)
                  .length}
              </span>
            </button>
          ))}
        </div>
        {detailId && !urlDetail && <p className="state" role="status">{t("Loading Flare…")}</p>}
        {detailId && urlDetail && !urlDetail.value && (
          <p className="state" role={urlDetail.error ? "alert" : "status"}>
            {urlDetail.error ? message(urlDetail.error) : t("Flare not found.")}
          </p>
        )}
        {loading ? (
          <p className="state" role="status">
            {t("Loading Flares…")}</p>
        ) : error ? (
          <p className="state error-text" role="alert">
            {message(error)}
          </p>
        ) : !insights.length ? (
          <div className="state insights-empty-state">
            <span className="empty-state-icon" aria-hidden="true">
              <Icon name="note" />
            </span>
            <h2>{itemCount ? t(itemCount === 1 ? "rememberedItem" : "rememberedItems", { count: itemCount }) : t("No Flares yet")}</h2>
            <p>
              {itemCount
                ? t("No completed Flares are available for this workspace.")
                : t("Add a note to keep project context here.")}
            </p>
            {!itemCount && (
              <>
                <div className="form-actions">
                  <button
                    className="button primary"
                    onClick={() => {
                      openCapture();
                    }}
                  >
                    {t("Add context")}</button>
                  <Link
                    className="button"
                    href="/sources"
                    onClick={() => {
                      void dataProvider.trackEvent({
                        eventType: "screen_opened",
                        targetType: "screen",
                        metadata: { screen: "sources_from_insights" },
                      });
                    }}
                  >
                    {t("Import from Obsidian")}</Link>
                </div>
              </>
            )}
          </div>
        ) : !visible.length ? (
          <div className="state">
            <h2>{t("No Flares in this category")}</h2>
            <p>{t("Choose another filter to review the available Flares.")}</p>
          </div>
        ) : (
          <div className="insight-stack">
            {visible.map((insight) => (
              <article
                key={insight.id}
                className={`card insight-card ${active?.id === insight.id ? "active" : ""}`}
                role="button"
                tabIndex={0}
                aria-expanded={active?.id === insight.id}
                aria-controls={
                  active?.id === insight.id ? "insight-evidence" : undefined
                }
                onClick={(event) => {
                  if (
                    (event.target as Element).closest(
                      "a, button, input, select, textarea",
                    )
                  )
                    return;
                  toggleInsight(insight.id);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    toggleInsight(insight.id);
                  }
                }}
              >
                <div className="card-meta">
                  <span
                    className={`badge kind-${flareTypes.indexOf(flareTypeFor(insight))}`}
                  >
                    <span className="dot" />
                    {label(flareTypeFor(insight))}
                  </span>
                  <span className="muted">
                    {new Date(insight.createdAt).toLocaleDateString(locale, {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                  {active?.id === insight.id && (
                    <span className="selected-label">
                      {t("Selected")}{" "}<Icon name="check" />
                    </span>
                  )}
                </div>
                <h2>{insight.title}</h2>
                <p className="description">{insight.statement}</p>
                {insight.action && <p className="description"><strong>{t("Next action:")} </strong>{insight.action}</p>}
                <div className="callout">
                  <Icon name="info" />
                  <p>
                    <strong>{t("Why it matters")}</strong>
                    <span>{insight.reason}</span>
                  </p>
                </div>
                <footer className="card-footer">
                  <span>
                    <Icon name="sources" />
                    {insight.evidence.length} {" "}{t("sources")}</span>
                </footer>
              </article>
            ))}
          </div>
        )}
      </section>
      {active && (
        <aside
          className="evidence-panel"
          id="insight-evidence"
          aria-label={t("Flare evidence")}
        >
          <header>
            <h2>
              <Icon name="note" />
              {" "}{t("Flare Evidence")}</h2>
            <button
              className="icon-button"
              aria-label={t("Close evidence")}
              onClick={closePanel}
            >
              <Icon name="close" />
            </button>
          </header>
          <div className="evidence-body">
            <p className="eyebrow accent">{label(flareTypeFor(active))}</p>
            <h2>{active.title}</h2>
            <div className="card attention">
              <h3>{t("Why this requires attention")}</h3>
              <p>{active.reason}</p>
            </div>
            <h3 className="eyebrow muted">{t("VERIFIABLE QUOTES")}</h3>
            {active.evidence.map((e, i) => (
              <article className="quote-card" key={`${e.itemId}-${i}`}>
                <div className="quote-meta">
                  <Link onClick={() => { void dataProvider.trackEvent({ eventType: "voluntary_inspection", interactionId: crypto.randomUUID(), flareId: active.id, sourceId: e.itemId }); }} href={`/vault?item=${encodeURIComponent(e.itemId)}`}>{e.sourceTitle}</Link>
                  <span className="muted">{label(e.sourceType)}</span>
                </div>
                <blockquote>“{e.excerpt}”</blockquote>
                <Link onClick={() => { void dataProvider.trackEvent({ eventType: "voluntary_inspection", interactionId: crypto.randomUUID(), flareId: active.id, sourceId: e.itemId }); }} className="text-button" href={`/vault?item=${encodeURIComponent(e.itemId)}`}>
                  {t("Open source")}{" "}<Icon name="arrow" />
                </Link>
              </article>
            ))}
          </div>
          <footer className="evidence-actions">
            <button
              className="button primary"
              onClick={() =>
                openCapture(
                  t("resolutionDraft", { title: active.title, reason: active.reason, evidence: active.evidence.map((e) => `- ${e.sourceTitle}: ${e.excerpt}`).join("\n") }),
                )
              }
            >
              <Icon name="note" />
              {" "}{t("Draft Resolution Note")}</button>
          </footer>
        </aside>
      )}
    </div>
  );
}
