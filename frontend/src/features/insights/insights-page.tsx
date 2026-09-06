"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  dataProvider,
  dataProviderMode,
  type Insight,
  type InsightKind,
} from "@/lib/data";
import { Icon } from "@/components/icons";
import { useWorkspace } from "@/components/workspace-context";
const kinds: InsightKind[] = [
  "Contradiction",
  "Repeated Problem",
  "Hidden Connection",
  "Unresolved Question",
];
const plural: Record<InsightKind, string> = {
  Contradiction: "Contradictions",
  "Repeated Problem": "Repeated Problems",
  "Hidden Connection": "Hidden Connections",
  "Unresolved Question": "Unresolved Questions",
};
export function InsightsPage() {
  const params = useSearchParams();
  const [insights, setInsights] = useState<Insight[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [filter, setFilter] = useState<InsightKind | "All">("All");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const { openCapture } = useWorkspace();
  useEffect(() => {
    let live = true;
    void dataProvider
      .listInsights()
      .then((list) => {
        if (live) {
          setError("");
          setInsights(list);
          setSelected(params.get("insight"));
        }
      })
      .catch(() => {
        if (live)
          setError("Insights could not be loaded. Refresh to try again.");
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [params]);
  const visible = insights.filter((i) => filter === "All" || i.kind === filter);
  const active = panelOpen ? visible.find((i) => i.id === selected) : undefined;
  useEffect(() => {
    if (!panelOpen) return;
    const outside = (event: PointerEvent) => {
      if (
        event.target instanceof Element &&
        !event.target.closest(".evidence-panel, .insight-card")
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
    const opening = !panelOpen || selected !== id;
    setSelected(id);
    setPanelOpen(opening);
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
            RECENT DISCOVERIES · {insights.length} INSIGHTS DETECTED
          </p>
          <h1>Insights</h1>
          <p>
            Important patterns, contradictions, and recurring questions quietly
            surfaced across team channels, PRs, and documents.
          </p>
        </header>
        <div className="filters">
          <button
            className={`filter ${filter === "All" ? "selected" : ""}`}
            onClick={() => {
              setFilter("All");
              setPanelOpen(false);
            }}
          >
            All <span>{insights.length}</span>
          </button>
          {kinds.map((kind) => (
            <button
              key={kind}
              className={`filter ${filter === kind ? "selected" : ""}`}
              onClick={() => {
                setFilter(kind);
                setSelected(insights.find((i) => i.kind === kind)?.id ?? null);
                setPanelOpen(false);
              }}
            >
              {plural[kind]}{" "}
              <span>{insights.filter((i) => i.kind === kind).length}</span>
            </button>
          ))}
        </div>
        {loading ? (
          <p className="state" role="status">
            Loading discoveries…
          </p>
        ) : error ? (
          <p className="state error-text" role="alert">
            {error}
          </p>
        ) : !visible.length ? (
          <div className="state">
            <h2>No discoveries in this category</h2>
            <p>Choose another filter to explore the available evidence.</p>
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
                    className={`badge kind-${kinds.indexOf(insight.kind ?? "Hidden Connection")}`}
                  >
                    <span className="dot" />
                    {insight.kind}
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
                <p className="description">{insight.summary}</p>
                <div className="callout">
                  <Icon name="info" />
                  <p>
                    <strong>Why it matters</strong>
                    <span>{insight.explanation}</span>
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
          aria-label="Insight evidence"
        >
          <header>
            <h2>
              <Icon name="note" />
              Insight Evidence
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
            <p className="eyebrow accent">{active.kind}</p>
            <h2>{active.detailTitle ?? active.title}</h2>
            <div className="card attention">
              <h3>Why this requires attention</h3>
              <p>{active.explanation}</p>
            </div>
            <h3 className="eyebrow muted">VERIFIABLE QUOTES</h3>
            {dataProviderMode === "api" && (
              <p className="muted">
                Demo insight: these evidence sources are not stored in the
                workspace database yet.
              </p>
            )}
            {active.evidence.map((e, i) => (
              <article className="quote-card" key={`${e.itemId}-${i}`}>
                <div className="quote-meta">
                  {dataProviderMode === "mock" ? (
                    <Link href={`/vault?item=${e.itemId}`}>{e.sourceTitle}</Link>
                  ) : (
                    <span>{e.sourceTitle}</span>
                  )}
                  <span className="muted">{e.sourceType}</span>
                </div>
                <blockquote>“{e.excerpt}”</blockquote>
                {dataProviderMode === "mock" ? (
                  <Link
                    className="text-button"
                    href={`/vault?item=${e.itemId}`}
                  >
                    Open source <Icon name="arrow" />
                  </Link>
                ) : (
                  <span className="muted">Demo source</span>
                )}
              </article>
            ))}
          </div>
          <footer className="evidence-actions">
            <button
              className="button primary"
              onClick={() =>
                openCapture(
                  `Resolution note: ${active.detailTitle ?? active.title}\n\n${active.explanation}\n\nEvidence:\n${active.evidence.map((e) => `- ${e.sourceTitle}: ${e.excerpt}`).join("\n")}\n\nDecision: `,
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
