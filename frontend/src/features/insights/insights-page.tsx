"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  dataProvider,
  dataProviderMode,
  type Insight,
} from "@/lib/data";
import { Icon } from "@/components/icons";
import { useWorkspace } from "@/components/workspace-context";
const flareTypes = ["Discovery", "Reminder", "Warning"] as const;
type FlareType = (typeof flareTypes)[number];
const plural: Record<FlareType, string> = {
  Discovery: "Discoveries",
  Reminder: "Reminders",
  Warning: "Warnings",
};
const flareTypeFor = (insight: Insight): FlareType =>
  insight.flareType ??
  (insight.kind === "Contradiction"
    ? "Warning"
    : insight.kind === "Hidden Connection"
      ? "Discovery"
      : "Reminder");
export function InsightsPage() {
  const params = useSearchParams();
  const [insights, setInsights] = useState<Insight[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
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
          setSelected(params.get("insight"));
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
  }, [params, revision]);
  const visible = insights.filter(
    (insight) => filter === "All" || flareTypeFor(insight) === filter,
  );
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
            RECENT FLARES · {insights.length} SURFACED
          </p>
          <h1>Flares</h1>
          <p>Things you might have missed, forgotten, or contradicted.</p>
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
          {flareTypes.map((kind) => (
            <button
              key={kind}
              className={`filter ${filter === kind ? "selected" : ""}`}
              onClick={() => {
                setFilter(kind);
                setSelected(
                  insights.find((insight) => flareTypeFor(insight) === kind)
                    ?.id ?? null,
                );
                setPanelOpen(false);
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
                ? "Keep adding context. Flares appear when there is enough evidence."
                : "Flare needs context before it can notice anything."}
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
                  Add notes, files, or voice memos. Flare will surface connections as your context grows.
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
