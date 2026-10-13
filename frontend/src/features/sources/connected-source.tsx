"use client";
import { useEffect, useRef, useState } from "react";
import { Dialog } from "@/components/dialog";
import { Icon } from "@/components/icons";
import { useI18n } from "@/i18n/provider";
import { dataProvider, type ConnectedProvider, type SourceConnection, type SourceResource } from "@/lib/data";

export function sourceFailure(cause: unknown): string {
  const failure = cause as { code?: string; status?: number };
  if (failure?.status === 401) return "errorSession";
  if (failure?.status === 403) return "errorPermission";
  if (failure?.code === "selection_changed") return "Source selection changed. Check status and choose again.";
  if (failure?.code === "selection_consent_required") return "Confirm sharing before saving your selection.";
  if (failure?.code === "authorization_lost" || failure?.code === "offline_access_unavailable") return "Reconnect this source to restore access.";
  if (failure?.code === "github_repository_required") return "Connect GitHub and choose a repository first.";
  if (failure?.code === "source_worker_unavailable") return "Sync is temporarily unavailable. Your selection is saved.";
  if (failure?.code === "rate_limited") return "The source asked us to wait. Check status later.";
  if (failure?.code === "import_request_timeout") return "The request timed out. Check status before trying again.";
  return "Source operation could not complete. Check status before trying again.";
}

export function ConnectedSource({ provider, connection, available, syncAvailable, refresh }: {
  provider: ConnectedProvider; connection?: SourceConnection; available: boolean; syncAvailable: boolean; refresh: () => Promise<void>;
}) {
  const { t, label, message } = useI18n();
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [open, setOpen] = useState(false), [loading, setLoading] = useState(false);
  const [resources, setResources] = useState<SourceResource[]>([]), [selected, setSelected] = useState<string[]>([]);
  const [cursor, setCursor] = useState<string | null>(null), [revision, setRevision] = useState(0), [consent, setConsent] = useState(false);
  const pending = useRef<AbortController | null>(null), dialogEpoch = useRef(0), writePending = useRef(false);
  useEffect(() => () => { pending.current?.abort(); dialogEpoch.current++; }, []);
  const connected = !!connection && !["pending", "disabled"].includes(connection.status);
  const active = !!connection?.job && ["queued", "processing", "retry_wait"].includes(connection.job.status);
  async function action(run: (signal: AbortSignal) => Promise<unknown>) {
    if (writePending.current) return;
    writePending.current = true; setBusy(true); setError("");
    const controller = new AbortController(); pending.current = controller;
    try { await run(controller.signal); await refresh(); }
    catch (cause) { if (!controller.signal.aborted) setError(sourceFailure(cause)); }
    finally { if (pending.current === controller) { pending.current = null; setBusy(false); } writePending.current = false; }
  }
  async function loadResources(next?: string) {
    if (!connection) return;
    const epoch = ++dialogEpoch.current; setLoading(true); setError("");
    const controller = new AbortController(); pending.current?.abort(); pending.current = controller;
    try {
      const page = await dataProvider.sourceResources(connection.id, next, controller.signal);
      if (controller.signal.aborted || epoch !== dialogEpoch.current) return;
      setRevision(page.scopeRevision); setCursor(page.cursor);
      setResources(previous => Array.from(new Map([...(next ? previous : connection.resources), ...page.resources].map(item => [item.id, item])).values()));
    } catch (cause) { if (!controller.signal.aborted && epoch === dialogEpoch.current) setError(sourceFailure(cause)); }
    finally { if (epoch === dialogEpoch.current) { setLoading(false); pending.current = null; } }
  }
  function close() { if (busy) return; dialogEpoch.current++; pending.current?.abort(); pending.current = null; setLoading(false); setOpen(false); }
  function choose() { setSelected(connection?.resources.map(item => item.id) ?? []); setConsent(false); setOpen(true); void loadResources(); }
  const counts = connection?.job ?? connection?.lastResult;
  return <div className="github-source-controls">
    <p className="muted meta">{!available ? t("Connection is not enabled yet.") : !connected ? t("Read-only sync of selected context.") : connection?.owner ? connection.accountLabel : t("Managed by a teammate.")}</p>
    {connected && <>
      <p className="muted meta">{active ? t("Syncing selected context…") : connection?.status === "error" ? t("Sync needs attention.") : connection?.enabled ? t(syncAvailable ? "Selected context syncs automatically." : "Selection saved. Sync is paused.") : t("Choose context to start syncing.")}</p>
      {connection?.job?.status === "cancelled" && <p role="status" className="muted meta">{t("Sync cancelled. Context already saved in Vault is kept.")}</p>}
      {connection?.resources.length ? <div className="tags">{connection.resources.map(item => <span key={item.id}>{item.name}</span>)}</div> : null}
      {counts && <p className="muted meta" role="status">{t("sourceSyncCounts", {added: counts.added, updated: counts.updated, unchanged: counts.unchanged, skipped: counts.skipped, conflicts: counts.conflicts})}{counts.more ? ` ${t("More context will continue in the next batch.")}` : ""}</p>}
      {connection?.lastSyncAt && <p className="muted meta">{t("Last completed sync")}: {new Date(connection.lastSyncAt).toLocaleString()}</p>}
      {connection?.errorCode && <p role="status" className="error-text">{t(connection.errorCode === "workspace_storage_limit" ? "Workspace storage limit reached. Sync is paused." : connection.errorCode === "authorization_lost" ? "Reconnect this source to restore access." : connection.errorCode === "rate_limited" ? "The source asked us to wait. Check status later." : "Sync needs attention.")}</p>}
      {!syncAvailable && <p className="muted meta">{t("Sync is temporarily unavailable. Your selection is saved.")}</p>}
    </>}
    {error && <p className="error-text" role="alert">{message(error)}</p>}
    <div className="tags">
      {!connected && <button type="button" className="button" disabled={!available || busy || !!connection && !connection.owner} onClick={() => void action(async signal => { const result = await dataProvider.connectSource(provider, signal); if (result.url) window.location.assign(result.url); })}>{busy ? t("Connecting…") : t("Connect")}</button>}
      {connected && connection?.owner && <>
        <button type="button" className="button" disabled={!available || busy} onClick={choose}>{t("Choose context")}</button>
        <button type="button" className="button" disabled={!syncAvailable || busy || !connection.enabled || active} onClick={() => void action(signal => dataProvider.sourceConnectionAction(connection.id, "sync", signal))}>{t("Sync now")}</button>
        {active && <button type="button" className="button" disabled={busy} onClick={() => void action(signal => dataProvider.sourceConnectionAction(connection.id, "cancel", signal))}>{t("Cancel sync")}</button>}
        {connection.status === "error" && <button type="button" className="button" disabled={!available || busy} onClick={() => void action(async signal => { const result = await dataProvider.connectSource(provider, signal); if (result.url) window.location.assign(result.url); })}>{t("Reconnect")}</button>}
      </>}
      {connection?.canDisconnect && !["pending", "disabled"].includes(connection.status) && <button type="button" className="button" disabled={busy} onClick={() => void action(signal => dataProvider.sourceConnectionAction(connection.id, "disconnect", signal))}>{t("Disconnect")}</button>}
      <button type="button" className="button" disabled={busy} onClick={() => void action(() => refresh())}>{t("Check status")}</button>
    </div>
    {connected && <p className="muted meta">{t("Disconnect stops future sync. Saved Vault context stays available.")}</p>}
    {open && <Dialog title={t("Choose context")} onClose={close} className="zip-dialog">
      <header className="zip-dialog-header"><div><p className="eyebrow">{label(provider === "drive" ? "Google Drive" : provider === "github" ? "GitHub" : provider === "gmail" ? "Gmail" : provider === "notion" ? "Notion" : "Slack")}</p><h2>{t("Choose context")}</h2></div><button className="icon-button" type="button" disabled={busy} aria-label={t("Close")} onClick={close}><Icon name="close" /></button></header>
      <p className="muted">{t("Only your selection is copied into this workspace. Up to 20 sources.")}</p>
      <div style={{ maxHeight: "40vh", overflowY: "auto" }}>
        {resources.map(resource => <label className="setting-row" key={resource.id} style={{ display: "flex", justifyContent: "flex-start", gap: 12, padding: "12px 0" }}>
          <input type="checkbox" style={{ width: 18, height: 18, flexShrink: 0, margin: 0 }} checked={selected.includes(resource.id)} disabled={busy || !selected.includes(resource.id) && selected.length >= 20} onChange={event => setSelected(previous => event.target.checked ? [...previous, resource.id] : previous.filter(id => id !== resource.id))} /><span style={{ overflowWrap: "anywhere" }}>{resource.name}</span>
        </label>)}
      </div>
      {loading ? <p className="muted" role="status">{t("Loading context…")}</p> : resources.length === 0 ? <p className="muted">{t("No accessible context found.")}</p> : null}
      {cursor && <button type="button" className="button" disabled={loading || busy} onClick={() => void loadResources(cursor)}>{t("Load more")}</button>}
      <label className="setting-row" style={{ display: "flex", justifyContent: "flex-start", gap: 12, padding: "16px 0" }}><input type="checkbox" style={{ width: 18, height: 18, flexShrink: 0, margin: 0 }} checked={consent} disabled={busy} onChange={event => setConsent(event.target.checked)} /><span>{t("I agree to share the selected content with everyone in this workspace, including after disconnecting.")}</span></label>
      <p className="muted meta">{t("Sync saves context. Analysis follows your workspace schedule.")}</p>
      {error && <p className="error-text" role="alert">{message(error)}</p>}
      <button type="button" className="button primary" disabled={busy || loading || !revision || selected.length > 0 && !consent} onClick={() => { if (!connection) return; void action(async signal => { await dataProvider.selectSourceResources(connection.id, revision, selected, consent, signal); setOpen(false); }); }}>{busy ? t("Saving…") : t("Save selection")}</button>
    </Dialog>}
  </div>;
}
