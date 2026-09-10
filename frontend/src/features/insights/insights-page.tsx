"use client";
import Link from "next/link";
import { AnalyzeAction } from "@/features/analyze/analyze-action";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  dataProvider,
  type Insight,
} from "@/lib/data";
import { Icon } from "@/components/icons";
import { useWorkspace } from "@/components/workspace-context";
const flareTypes = ["Reminder", "Warning", "Recommendation"] as const;
type FlareType = (typeof flareTypes)[number];
const plural: Record<FlareType, string> = {
  Reminder: "Reminders", Warning: "Warnings", Recommendation: "Recommendations",
};
const flareTypeFor = (insight: Insight): FlareType => insight.type;
export function InsightsPage() {
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
  }, [detailId, revision]);
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
      )
        setPanelOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPanelOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [panelOpen]);
  const toggleInsight = (id: string) => {
    const opening = !panelOpen || active?.id !== id;
    setSelected(insights.find((insight) => insight.id === id) ?? null);
    setPanelOpen(opening);
    if (opening && detailId !== id) {
      const url = new URL(window.location.href);
      url.searchParams.set("insight", id);
      window.history.pushState(null, "", url);
    }
    if (!opening) return;
    if (window.innerWidth <= 1050)
      requestAnimationFrame(() =>
        document
          .querySelector(".evidence-panel")
          ?.scrollIntoView({ block: "start" }),
      );
  };
  return (
    <div className={`insights-layout ${active ? "with-evidence" : ""}`}>
      <section className="page insight-feed">
        <header className="page-heading">
          <p className="eyebrow">
            <span className="dot" />
            RECENT FLARES · {insights.length} SURFACED
          </p>
          <h1>Flares</h1>
          <p>Things you might have missed, forgotten, or contradicted.</p>
        </header>
        <AnalyzeAction />
        <div className="filters">
          <button
            className={`filter ${filter === "All" ? "selected" : ""}`}
            onClick={() => {
              setFilter("All");
            }}
          >
            All <span>{insights.length}</span>
          </button>
          {flareTypes.map((kind) => (
            <button
              key={kind}
              className={`filter ${filter === kind ? "selected" : ""}`}
              onClick={() => {
                setFilter(kind);
              }}
            >
              {plural[kind]}{" "}
              <span>
                {insights.filter((insight) => flareTypeFor(insight) === kind)
                  .length}
              </span>
            </button>
          ))}
        </div>
        {detailId && !urlDetail && <p className="state" role="status">Loading Flare…</p>}
        {detailId && urlDetail && !urlDetail.value && (
          <p className="state" role={urlDetail.error ? "alert" : "status"}>
            {urlDetail.error || "Flare not found."}
          </p>
        )}
        {loading ? (
          <p className="state" role="status">
            Loading Flares…
          </p>
        ) : error ? (
          <p className="state error-text" role="alert">
            {error}
          </p>
        ) : !insights.length ? (
          <div className="state">
            <h2>{itemCount ? `${itemCount} item${itemCount === 1 ? "" : "s"} remembered` : "No Flares yet"}</h2>
            <p>
              {itemCount
                ? "No completed Flares are available for this workspace."
                : "Add a note to keep project context here."}
            </p>
            {!itemCount && (
              <>
                <div className="form-actions">
                  <button className="button primary" onClick={() => openCapture()}>
                    Add context
                  </button>
                  <Link className="button" href="/sources">
                    Import from Obsidian
                  </Link>
                </div>
                <p className="muted meta">
                  Saved notes remain available in your Vault.
                </p>
              </>
            )}
          </div>
        ) : !visible.length ? (
          <div className="state">
            <h2>No Flares in this category</h2>
            <p>Choose another filter to review the available Flares.</p>
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
                    {flareTypeFor(insight)}
                  </span>
                  <span className="muted">
                    {new Date(insight.createdAt).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                  {active?.id === insight.id && (
                    <span className="selected-label">
                      Selected <Icon name="check" />
                    </span>
                  )}
                </div>
                <h2>{insight.title}</h2>
                <p className="description">{insight.statement}</p>
                {insight.action && <p className="description"><strong>Next action: </strong>{insight.action}</p>}
                <div className="callout">
                  <Icon name="info" />
                  <p>
                    <strong>Why it matters</strong>
                    <span>{insight.reason}</span>
                  </p>
                </div>
                <footer className="card-footer">
                  <span>
                    <Icon name="sources" />
                    {insight.evidence.length} sources
                  </span>
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
          aria-label="Flare evidence"
        >
          <header>
            <h2>
              <Icon name="note" />
              Flare Evidence
            </h2>
            <button
              className="icon-button"
              aria-label="Close evidence"
              onClick={() => setPanelOpen(false)}
            >
              <Icon name="close" />
            </button>
          </header>
          <div className="evidence-body">
            <p className="eyebrow accent">{flareTypeFor(active)}</p>
            <h2>{active.title}</h2>
            <div className="card attention">
              <h3>Why this requires attention</h3>
              <p>{active.reason}</p>
            </div>
            <h3 className="eyebrow muted">VERIFIABLE QUOTES</h3>
            {active.evidence.map((e, i) => (
              <article className="quote-card" key={`${e.itemId}-${i}`}>
                <div className="quote-meta">
                  <Link href={`/vault?item=${encodeURIComponent(e.itemId)}`}>{e.sourceTitle}</Link>
                  <span className="muted">{e.sourceType}</span>
                </div>
                <blockquote>“{e.excerpt}”</blockquote>
                <Link className="text-button" href={`/vault?item=${encodeURIComponent(e.itemId)}`}>
                  Open source <Icon name="arrow" />
                </Link>
              </article>
            ))}
          </div>
          <footer className="evidence-actions">
            <button
              className="button primary"
              onClick={() =>
                openCapture(
                  `Resolution note: ${active.title}\n\n${active.reason}\n\nEvidence:\n${active.evidence.map((e) => `- ${e.sourceTitle}: ${e.excerpt}`).join("\n")}\n\nDecision: `,
                )
              }
            >
              <Icon name="note" />
              Draft Resolution Note
            </button>
          </footer>
        </aside>
      )}
    </div>
  );
}
