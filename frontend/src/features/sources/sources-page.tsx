"use client";
import { useEffect, useState } from "react";
import { dataProvider, type Source } from "@/lib/data";
import { Icon } from "@/components/icons";
import { useWorkspace } from "@/components/workspace-context";

export function SourcesPage() {
  const { openCapture } = useWorkspace();
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    void dataProvider.listSources()
      .then((list) => { if (live) setSources(list); })
      .catch(() => { if (live) setError("Sources could not be loaded."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);
  const groups = [
    { title: "Available now", sources: sources.filter((source) => source.status === "ready") },
    { title: "Coming soon", sources: sources.filter((source) => source.status === "coming-soon") },
  ];
  return (
    <section className="page sources-page">
      <header className="page-heading heading-row">
        <div>
          <h1>Sources</h1>
          <p>Ways to add project context to Flare.</p>
        </div>
        <div className="heading-actions">
          <span className="badge"><span className="dot green" />MVP</span>
        </div>
      </header>
      {error && <p role="alert" className="error-text">{error}</p>}
      {loading ? <p role="status" className="state">Loading sources…</p> : groups.map(({ title, sources }) => (
        <section className="source-group" key={title} aria-label={title}>
          <h2 className="source-group-title">{title}</h2>
          <div className="source-grid">
            {sources.map((source) => (
              <article className="card source-card" key={source.id}>
                <header>
                  <SourceIcon source={source} />
                  <div><h3>{source.name}</h3><p className="muted">{source.scope}</p></div>
                  <span className={`badge status-${source.status}`}>
                    <span className="dot" />{source.status === "ready" ? "Ready" : "Coming soon"}
                  </span>
                </header>
                <div className="source-scope">
                  <p className="eyebrow muted">{source.status === "ready" ? "AVAILABLE CONTEXT" : "MVP STATUS"}</p>
                  {source.channels.length ? (
                    <div className="tags">{source.channels.map((channel) => <span key={channel}>{channel}</span>)}</div>
                  ) : <p className="muted">Not available yet.</p>}
                </div>
                <p className="source-description">{source.description}</p>
                <p className="muted meta">{source.updated}</p>
                <footer>
                  <button className="button" disabled={source.status !== "ready"} onClick={() => openCapture()}>
                    {source.status === "ready" ? "Capture a Note" : "Coming soon"}
                  </button>
                </footer>
              </article>
            ))}
          </div>
        </section>
      ))}
    </section>
  );
}

function SourceIcon({ source }: { source: Source }) {
  const icon = source.id === "telegram" ? "arrow" : source.id === "github" ? "system"
    : source.id === "linear" ? "check" : source.id === "reviews" ? "sources" : "note";
  return <span className={`source-logo source-${source.id}`}><Icon name={icon} /></span>;
}
