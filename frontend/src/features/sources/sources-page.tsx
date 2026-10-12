"use client";
import { useI18n } from "@/i18n/provider";
import Link from "next/link";
import { ConnectedSource } from "./connected-source";
import type { ConnectedProvider, SourceConnections } from "@/lib/data";
import { ZipImport } from "./zip-import";
import { useEffect, useState } from "react";
import { dataErrorMessage, dataProvider, type GitHubRepository, type Source } from "@/lib/data";
import { Icon } from "@/components/icons";
import { Select } from "@/components/select";
import { useWorkspace } from "@/components/workspace-context";

export function SourcesPage() {
  const { t, label, message } = useI18n();

  const { openCapture } = useWorkspace();
  const [connections, setConnections] = useState<SourceConnections>({ providers: [], connections: [] });
  const [connectionError, setConnectionError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let running = false;
    async function check() {
      if (running) return;
      running = true;
      try { const state = await dataProvider.getSourceConnections(controller.signal); if (!controller.signal.aborted) { setConnections(state); setConnectionError(""); } }
      catch { if (!controller.signal.aborted) setConnectionError("Source status could not be loaded. Check status before trying again."); }
      finally { running = false; }
    }
    void check(); const timer = setInterval(() => void check(), 10000);
    return () => { controller.abort(); clearInterval(timer); };
  }, []);
  async function refreshConnections() { setConnections(await dataProvider.getSourceConnections()); setConnectionError(""); }
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [githubError, setGitHubError] = useState("");
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [selectedRepository, setSelectedRepository] = useState("");
  const [githubLoading, setGitHubLoading] = useState(false);
  const [githubAction, setGitHubAction] = useState<"" | "connect" | "save" | "disconnect">("");
  useEffect(() => {
    let live = true;
    void dataProvider.listSources()
      .then(async (list) => {
        if (!live) return;
        setSources(list);
        const github = list.find((source) => source.id === "github");
        if (github?.status === "syncing") {
          setGitHubLoading(true);
          try {
            const available = await dataProvider.listGitHubRepositories();
            if (live) setRepositories(available);
          } catch (cause) {
            if (live) setGitHubError(dataErrorMessage(cause, "Repositories could not be loaded."));
          } finally {
            if (live) setGitHubLoading(false);
          }
        }
      })
      .catch(() => { if (live) setError("Sources could not be loaded."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);
  async function refreshSources() {
    const list = await dataProvider.listSources();
    setSources(list);
    return list;
  }
  async function connectGitHub() {
    setGitHubAction("connect");
    setGitHubError("");
    try {
      window.location.assign(await dataProvider.startGitHubConnection());
    } catch (cause) {
      setGitHubError(dataErrorMessage(cause, "GitHub authorization could not start."));
      setGitHubAction("");
    }
  }
  async function saveGitHubRepository() {
    const repositoryId = Number(selectedRepository);
    if (!Number.isSafeInteger(repositoryId) || repositoryId <= 0) return;
    setGitHubAction("save");
    setGitHubError("");
    try {
      await dataProvider.selectGitHubRepository(repositoryId);
      await refreshSources();
      setRepositories([]);
      setSelectedRepository("");
    } catch (cause) {
      setGitHubError(dataErrorMessage(cause, "Repository could not be saved."));
    } finally {
      setGitHubAction("");
    }
  }
  async function disconnectGitHub() {
    setGitHubAction("disconnect");
    setGitHubError("");
    try {
      await dataProvider.disconnectGitHub();
      await refreshSources();
    } catch (cause) {
      setGitHubError(dataErrorMessage(cause, "GitHub could not be disconnected."));
    } finally {
      setGitHubAction("");
    }
  }
  const groups = [
    { title: "Available now", sources: sources.filter((source) => source.status !== "coming-soon") },
    { title: "Coming soon", sources: sources.filter((source) => source.status === "coming-soon") },
  ];
  return (
    <section className="page sources-page">
      <header className="page-heading heading-row">
        <div>
          <h1>{t("Sources")}</h1>
          <p>{t("Ways to add project context to Flare.")}</p>
        </div>
      </header>
      {connectionError && <p role="alert" className="error-text">{message(connectionError)}</p>}
      {error && <p role="alert" className="error-text">{message(error)}</p>}
      {loading ? <p role="status" className="state">{t("Loading sources…")}</p> : groups.map(({ title, sources }) => (
        <section className="source-group" key={title} aria-label={label(title)}>
          <h2 className="source-group-title">{label(title)}</h2>
          <div className="source-grid">
            {sources.map((source) => (
              <article className="card source-card" key={source.id}>
                <header>
                  <SourceIcon source={source} />
                  <div><h3>{label(source.name)}</h3><p className="muted">{source.repository ? source.scope : label(source.scope)}</p></div>
                  <span className={`badge status-${source.status}`}>
                    <span className="dot" />{label(sourceStatus(source))}
                  </span>
                </header>
                {!["notion", "obsidian", "slack", "gmail", "drive"].includes(source.id) && <div className="source-scope">
                  <p className="eyebrow muted">{source.status === "ready" ? t("AVAILABLE CONTEXT") : t("PRIMARY")}</p>
                  {source.channels.length ? (
                    <div className="tags">{source.channels.map((channel) => <span key={channel}>{source.status === "connected" ? channel : label(channel)}</span>)}</div>
                  ) : source.status === "connected" ? null : <p className="muted">{t("Not available yet.")}</p>}
                </div>}
                <p className="source-description">{source.id === "notion" || source.id === "obsidian" ? t("ZIP snapshots with Markdown, TXT and CSV. Files are checked and added together. Analysis follows your workspace schedule.") : label(source.description)}</p>
                {source.id !== "notion" && source.id !== "obsidian" && <p className="muted meta">{source.id === "github" && source.status === "syncing" ? t("authorizedAs", { name: source.accountLogin ?? "GitHub" }) : label(source.updated)}</p>}
                <footer>
                  {["slack", "gmail", "drive", "notion", "github"].includes(source.id) && <ConnectedSource provider={source.id as ConnectedProvider} connection={connections.connections.find(item => item.provider === source.id)} available={connections.providers.some(item => item.provider === source.id && item.available)} syncAvailable={connections.providers.some(item => item.provider === source.id && item.syncAvailable)} refresh={refreshConnections} />}

                  {source.id === "notion" || source.id === "obsidian" ? (
                    <>
                      <ZipImport sourceKind={source.id} />
                      <Link className="zip-guide-link" href={`/settings/import-guides/${source.id}`}>
                        {t("View import guide")}</Link>
                    </>
                  ) : ["slack", "gmail", "drive"].includes(source.id) ? null : source.status === "manual-import" ? (
                    <Link className="button" href={`/settings/import-guides/${source.id}`}>
                      {t("View import guide")}</Link>
                  ) : source.id === "github" && source.repository ? null : source.id === "github" && source.status !== "coming-soon" ? (
                    <GitHubControls
                      source={source}
                      repositories={repositories}
                      selectedRepository={selectedRepository}
                      loading={githubLoading}
                      action={githubAction}
                      error={githubError || (source.error ? "genericError" : "")}
                      onSelect={setSelectedRepository}
                      onConnect={() => void connectGitHub()}
                      onSave={() => void saveGitHubRepository()}
                      onDisconnect={() => void disconnectGitHub()}
                    />
                  ) : (
                    <button className="button" disabled={source.status !== "ready"} onClick={() => openCapture()}>
                      {source.status === "ready" ? t("Capture a Note") : t("Coming soon")}
                    </button>
                  )}
                </footer>
              </article>
            ))}
          </div>
        </section>
      ))}
    </section>
  );
}

function sourceStatus(source: Source) {
  if (source.status === "ready") return "Ready";
  if (source.status === "manual-import") return "Manual import";
  if (source.status === "connected") return "Connected";
  if (source.status === "syncing") return "Select repository";
  if (source.status === "disconnected") return "Not connected";
  if (source.status === "error") return "Connection error";
  return "Coming soon";
}

type GitHubControlsProps = {
  source: Source;
  repositories: GitHubRepository[];
  selectedRepository: string;
  loading: boolean;
  action: "" | "connect" | "save" | "disconnect";
  error: string;
  onSelect(value: string): void;
  onConnect(): void;
  onSave(): void;
  onDisconnect(): void;
};

export function GitHubControls({ source, repositories, selectedRepository, loading, action, error,
  onSelect, onConnect, onSave, onDisconnect }: GitHubControlsProps) {
  const { t, message } = useI18n();

  if (source.status === "connected" && source.repository) {
    return <div className="github-source-controls">
      <div className="github-repository">
        <strong>{source.repository.fullName}</strong>
        <span className="muted">{t("Read-only connection")}</span>
      </div>
      {error && <p className="error-text" role="alert">{message(error)}</p>}
      <button className="button" disabled={action !== ""} onClick={onDisconnect}>
        {action === "disconnect" ? t("Disconnecting…") : t("Disconnect")}
      </button>
    </div>;
  }
  if (source.status === "syncing") {
    return <div className="github-source-controls">
      {loading ? <p className="muted" role="status">{t("Loading repositories…")}</p> : (
        <label className="github-repository-picker">
          {t("Repository")}{" "}<Select
            aria-label={t("Repository")}
            value={selectedRepository}
            placeholder={t("Select one repository…")}
            disabled={action !== "" || repositories.length === 0}
            onValueChange={onSelect}
            options={repositories.map((repository) => ({ value: String(repository.id), label: repository.fullName }))}
          />
        </label>
      )}
      {!loading && repositories.length === 0 && !error && <p className="muted">{t("No accessible repositories found.")}</p>}
      {error && <p className="error-text" role="alert">{message(error)}</p>}
      <button className="button" disabled={loading || !selectedRepository || action !== ""} onClick={onSave}>
        {action === "save" ? t("Saving…") : t("Save repository")}
      </button>
    </div>;
  }
  return <div className="github-source-controls">
    {error && <p className="error-text" role="alert">{message(error)}</p>}
    <button className="button" disabled={action !== ""} onClick={onConnect}>
      {action === "connect" ? t("Connecting…") : source.status === "error" ? t("Retry connection") : t("Connect GitHub")}
    </button>
  </div>;
}

function SourceIcon({ source }: { source: Source }) {
  const icon = source.id === "telegram" ? "arrow" : source.id === "github" ? "system"
    : source.id === "linear" ? "check" : source.id === "reviews" ? "sources" : "note";
  return <span className={`source-logo source-${source.id}`}><Icon name={icon} /></span>;
}
