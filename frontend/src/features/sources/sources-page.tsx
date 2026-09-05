"use client";
import { useEffect, useState } from "react";
import { dataProvider, type Source } from "@/lib/data";
import { Icon } from "@/components/icons";
import { Dialog } from "@/components/dialog";
import { useWorkspace } from "@/components/workspace-context";
export function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [editing, setEditing] = useState<Source | null>(null);
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const { refresh } = useWorkspace();
  useEffect(() => {
    let live = true;
    void dataProvider
      .listSources()
      .then((list) => {
        if (live) setSources(list);
      })
      .catch(() => {
        if (live) setError("Sources could not be loaded.");
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);
  const save = async (source: Source) => {
    setBusy(true);
    setError("");
    try {
      await dataProvider.saveSource(source);
      setSources(await dataProvider.listSources());
      setEditing(null);
      setAdding(false);
      refresh();
    } catch {
      setError("Could not save source settings in this browser. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="page sources-page">
      <header className="page-heading heading-row">
        <div>
          <h1>Sources</h1>
          <p>Services Flare is quietly listening to for project context.</p>
        </div>
        <div className="heading-actions">
          <span className="badge">
            <span className="dot green" />
            Demo workspace
          </span>
          <button className="button primary" onClick={() => setAdding(true)}>
            <Icon name="plus" />
            Add source
          </button>
        </div>
      </header>
      {error && (
        <p role="alert" className="error-text">
          {error}
        </p>
      )}
      {loading ? (
        <p role="status" className="state">
          Loading sources…
        </p>
      ) : (
        <div className="source-grid">
          {sources.map((source) => (
            <article
              className={`card source-card ${source.status === "disconnected" ? "needs-attention" : ""} ${source.providers?.length ? "has-providers" : ""}`}
              key={source.id}
            >
              <header>
                <SourceIcon source={source} />
                <div>
                  <h2>{source.name}</h2>
                  <p className="muted">{source.scope}</p>
                </div>
                <span className={`badge status-${source.status}`}>
                  <span className="dot" />
                  {source.status === "connected"
                    ? "Connected"
                    : source.status === "syncing"
                      ? "Syncing…"
                      : "Disconnected"}
                </span>
              </header>
              <div className="source-scope">
                <h3 className="eyebrow muted">
                  {source.status === "disconnected"
                    ? "STATUS"
                    : "MONITORED SCOPE"}
                </h3>
                {source.status === "disconnected" ? (
                  <p className="warning-text">
                    Authentication expired · Re-authorization required
                  </p>
                ) : source.providers?.length ? (
                  <div className="review-providers">
                    {source.providers.map((provider) => (
                      <div className="review-provider" key={provider.id}>
                        <div>
                          <strong>{provider.name}</strong>
                          <span className={`badge status-${provider.status}`}>
                            <span className="dot" />
                            {provider.status === "connected"
                              ? "Connected"
                              : "Disconnected"}
                          </span>
                        </div>
                        <p>{provider.selectedApps.join(" · ")}</p>
                        <small className="muted">{provider.updated}</small>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="tags">
                    {source.channels.map((channel) => (
                      <span key={channel}>{channel}</span>
                    ))}
                  </div>
                )}
              </div>
              <p className="source-description">{source.description}</p>
              <p className="muted meta">{source.updated}</p>
              <footer>
                <button
                  className={`button ${source.status === "disconnected" ? "primary" : ""}`}
                  disabled={busy}
                  onClick={() =>
                    source.status === "disconnected"
                      ? void save({
                          ...source,
                          status: "connected",
                          updated: "Reconnected just now (demo)",
                          description:
                            "Workspace discussions and team context.",
                        })
                      : setEditing(source)
                  }
                >
                  {source.status === "disconnected" && <Icon name="reset" />}
                  {source.status === "disconnected" ? "Reconnect" : "Configure"}
                </button>
              </footer>
            </article>
          ))}
        </div>
      )}
      {(editing || adding) && (
        <Dialog
          title={adding ? "Add source" : "Configure source"}
          onClose={() => {
            setEditing(null);
            setAdding(false);
          }}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const form = new FormData(e.currentTarget);
              const name = String(
                form.get("name") ?? editing?.name ?? "",
              ).trim();
              const providers = editing?.providers?.map((provider) => ({
                ...provider,
                selectedApps: String(form.get(`provider-${provider.id}`) ?? "")
                  .split(",")
                  .map((value) => value.trim())
                  .filter(Boolean),
                updated: "Configured just now (demo)",
              }));
              void save({
                id: editing?.id ?? crypto.randomUUID(),
                name,
                scope: String(form.get("scope") ?? ""),
                channels: providers
                  ? (editing?.channels ?? [])
                  : String(form.get("channels") ?? "")
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean),
                description:
                  editing?.description ?? "New workspace context source.",
                status: "connected",
                updated: "Configured just now (demo)",
                providers,
              });
            }}
          >
            <header className="sheet-header">
              <h2>{adding ? "Add source" : `Configure ${editing?.name}`}</h2>
              <button
                type="button"
                className="icon-button"
                aria-label="Close source settings"
                onClick={() => {
                  setEditing(null);
                  setAdding(false);
                }}
              >
                <Icon name="close" />
              </button>
            </header>
            <p className="muted">
              Demo connection settings. No external service is contacted.
            </p>
            {adding && (
              <label>
                Service name
                <input
                  name="name"
                  required
                  maxLength={60}
                  placeholder="Service name"
                />
              </label>
            )}
            <label>
              Workspace / scope
              <input name="scope" required defaultValue={editing?.scope} />
            </label>
            {editing?.providers ? (
              editing.providers.map((provider) => (
                <label key={provider.id}>
                  {provider.name} selected apps, separated by commas
                  <input
                    name={`provider-${provider.id}`}
                    required
                    defaultValue={provider.selectedApps.join(", ")}
                  />
                </label>
              ))
            ) : (
              <label>
                {editing?.id === "gmail"
                  ? "Monitored labels, separated by commas"
                  : "Channels or folders, separated by commas"}
                <input
                  name="channels"
                  required
                  defaultValue={editing?.channels.join(", ")}
                />
              </label>
            )}
            {error && (
              <p role="alert" className="error-text">
                {error}
              </p>
            )}
            <footer className="form-actions">
              <button className="button primary" disabled={busy}>
                {busy ? "Saving…" : "Save demo connection"}
              </button>
            </footer>
          </form>
        </Dialog>
      )}
    </section>
  );
}
function SourceIcon({ source }: { source: Source }) {
  const icon =
    source.id === "telegram"
      ? "arrow"
      : source.id === "github"
        ? "system"
        : source.id === "linear"
          ? "check"
          : source.id === "drive"
            ? "vault"
            : source.id === "reviews"
              ? "sources"
              : "note";
  return (
    <span className={`source-logo source-${source.id}`}>
      <Icon name={icon} />
    </span>
  );
}
