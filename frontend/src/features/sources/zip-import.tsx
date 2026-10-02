"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useI18n } from "@/i18n/provider";
import { dataProvider, type ImportPackage, type ImportPackageReport, type ZipSourceKind } from "@/lib/data";

export const isImportActive = (job: ImportPackage) => ["uploading", "staged", "queued", "processing", "retry_wait"].includes(job.status);
export const importPhaseLabel = (job: ImportPackage) => {
  if (job.status === "retry_wait") return "Waiting to retry";
  if (job.status === "failed") return "Import failed";
  if (job.status === "cancelled") return "Import cancelled";
  if (job.status === "expired") return "Import expired";
  if (job.status === "duplicate") return "Previously imported ZIP";
  if (job.status === "completed_with_skips") return "Imported with skipped files";
  if (job.status === "completed") return "Import complete";
  return { upload: "Uploading ZIP", inspect: "Inspecting ZIP", parse: "Reading files", publish: "Preparing sources", complete: "Import complete" }[job.phase];
};

export function importErrorLabel(code: string) {
  if (["unsafe_path", "path_collision", "special_entry"].includes(code)) return "ZIP contains unsafe or conflicting file paths.";
  if (["integrity_failure", "object_integrity", "malformed_zip", "dishonest_metadata"].includes(code)) return "ZIP is damaged or incomplete. Export it again.";
  if (code === "no_supported_content_or_incomplete") return "No supported UTF-8 Markdown, TXT or CSV files were found.";
  if (code === "authorization_revoked") return "Workspace write permission is required.";
  if (["expanded_bytes", "compressed_bytes", "file_bytes", "source_quota", "staged_quota", "chunk_bound", "manifest_bound", "expansion_ratio", "path_bound"].includes(code)) return "ZIP exceeds this workspace’s configured import limits.";
  return "Import could not continue. Check the file and try again.";
}

async function resolveImportReceipt(job: ImportPackage, history: ImportPackage[] = [], signal?: AbortSignal): Promise<ImportPackage> {
  if (job.status !== "duplicate") return job;
  if (!job.canonicalId || job.canonicalId === job.id) throw new Error("Missing canonical import");
  const canonical = history.find((entry) => entry.id === job.canonicalId)
    ?? await dataProvider.getImportPackage(job.canonicalId, signal);
  if (canonical.id !== job.canonicalId || canonical.sourceKind !== job.sourceKind || canonical.status === "duplicate") {
    throw new Error("Invalid canonical import");
  }
  return canonical;
}

export function ZipImport({ sourceKind }: { sourceKind: ZipSourceKind }) {
  const { t, label, message } = useI18n();
  const [capabilities, setCapabilities] = useState<{ available: boolean; maxUploadBytes: number | null } | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<ImportPackage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<ImportPackageReport | null>(null);
  const upload = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const epoch = useRef(0);
  const actionLock = useRef(false);
  const requestKey = useRef<{ file: File; key: string } | null>(null);
  useEffect(() => {
    mounted.current = true;
    let live = true;
    const controller = new AbortController();
    const initialEpoch = epoch.current;
    void dataProvider.getImportCapabilities().then((value) => {
      if (live) setCapabilities(value);
    }).catch(() => { if (live) setError("Import history could not be loaded."); });
    void dataProvider.listImportPackages().then(async (list) => {
      const recent = list.find((entry) => entry.sourceKind === sourceKind);
      const receipt = recent ? await resolveImportReceipt(recent, list, controller.signal) : null;
      if (live && epoch.current === initialEpoch) { setJob(receipt); setReport(null); }
    }).catch(() => { if (live && epoch.current === initialEpoch) setError("Import history could not be loaded."); });
    return () => { live = false; mounted.current = false; controller.abort(); upload.current?.abort(); };
  }, [sourceKind]);
  useEffect(() => {
    if (!job || !isImportActive(job) || job.status === "uploading" || job.status === "staged") return;
    let live = true;
    const pollEpoch = epoch.current;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void dataProvider.getImportPackage(job.id, controller.signal).then((next) => resolveImportReceipt(next, [], controller.signal)).then((next) => {
        if (live && epoch.current === pollEpoch) { setJob(next); setError(""); }
      }).catch(() => { if (live) setError("Import progress could not be loaded. Refresh to reconnect."); });
    }, 1500);
    return () => { live = false; clearTimeout(timer); controller.abort(); };
  }, [job]);

  function failure(cause: unknown) {
    const status = (cause as { status?: number })?.status;
    return status === 503 ? "ZIP import is unavailable in this environment." : status === 403 ? "Workspace write permission is required." : "Import could not continue. Check the file and try again.";
  }
  async function start() {
    if (!file || actionLock.current || !capabilities?.available) return;
    if (capabilities.maxUploadBytes !== null && file.size > capabilities.maxUploadBytes) { setError("ZIP exceeds this workspace’s configured import limits."); return; }
    actionLock.current = true;
    const operation = ++epoch.current;
    setBusy(true); setError(""); setReport(null);
    const controller = new AbortController(); upload.current = controller;
    try {
      if (!requestKey.current || requestKey.current.file !== file) requestKey.current = { file, key: crypto.randomUUID() };
      let session = job?.status === "uploading" && job.fileName === file.name && job.fileSize === file.size ? await dataProvider.getImportPackage(job.id) : null;
      if (session && !isImportActive(session)) { requestKey.current = { file, key: crypto.randomUUID() }; session = null; }
      session ??= await dataProvider.createImportPackage({ sourceKind, fileName: file.name, fileSize: file.size, requestKey: requestKey.current.key });
      if (controller.signal.aborted || !mounted.current || epoch.current !== operation) return;
      setJob(session);
      if (session.status === "uploading") await dataProvider.uploadImportPackage(session.id, file, controller.signal);
      if (controller.signal.aborted || !mounted.current || epoch.current !== operation) return;
      const next = await resolveImportReceipt(await dataProvider.importPackageAction(session.id, "finalize"), [], controller.signal);
      if (mounted.current && epoch.current === operation) { setJob(next); setFile(null); }
    } catch (cause) { if (mounted.current && epoch.current === operation && !controller.signal.aborted) setError(failure(cause)); }
    finally { if (mounted.current && epoch.current === operation) { actionLock.current = false; setBusy(false); } }
  }
  async function action(kind: "cancel" | "retry" | "finalize") {
    if (!job || (actionLock.current && kind !== "cancel")) return;
    const operation = ++epoch.current;
    actionLock.current = true;
    if (kind === "cancel") upload.current?.abort();
    setBusy(true); setError("");
    try { const next = await resolveImportReceipt(await dataProvider.importPackageAction(job.id, kind)); if (mounted.current && epoch.current === operation) { setJob(next); setReport(null); } }
    catch (cause) { if (mounted.current && epoch.current === operation) setError(failure(cause)); }
    finally { if (mounted.current && epoch.current === operation) { actionLock.current = false; setBusy(false); } }
  }
  async function loadReport(after = -1) {
    if (!job) return;
    const reportEpoch = epoch.current;
    setBusy(true); setError("");
    try {
      const next = await dataProvider.getImportPackageReport(job.id, after);
      if (mounted.current && epoch.current === reportEpoch) setReport((previous) => ({ ...next, entries: after < 0 ? next.entries : [...(previous?.entries ?? []), ...next.entries] }));
    } catch (cause) { if (mounted.current) setError(failure(cause)); }
    finally { if (mounted.current) setBusy(false); }
  }
  const complete = job && ["completed", "completed_with_skips"].includes(job.status);
  return <div className="capture-form">
    <p className="muted">{t("Import a ZIP snapshot. Markdown, TXT and CSV become sources together after all files are checked. Other files are skipped. Analyze runs only when you choose it.")}</p>
    {capabilities && !capabilities.available && <p role="status">{t("ZIP import is unavailable in this environment.")}</p>}
    <label>{t("ZIP export")}<input type="file" accept=".zip,application/zip" disabled={!capabilities?.available || busy || (!!job && isImportActive(job) && job.status !== "uploading")} onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
    <button className="button" disabled={!capabilities?.available || !file || busy || (!!job && isImportActive(job) && job.status !== "uploading")} onClick={() => void start()}>{busy ? t("Working…") : t("Import ZIP")}</button>
    {job && <section aria-label={t("ZIP import progress")}>
      <p role="status">{job.fileName} · {label(importPhaseLabel(job))}</p>
      {job.entryCount !== null && <p>{t("Checked files")}: {job.supportedCount + job.skippedCount + job.failedCount} / {job.entryCount} · {t("Supported")}: {job.supportedCount} · {t("Imported")}: {complete ? job.importedCount : 0} · {t("Skipped")}: {job.skippedCount} · {t("Failed")}: {job.failedCount}</p>}
      {!complete && isImportActive(job) && <p className="muted">{t("Sources stay private until the entire import completes.")}</p>}
      {job.errorCode && <p role="alert">{t("Import stopped")}: {message(importErrorLabel(job.errorCode))}</p>}
      {isImportActive(job) && <button className="button secondary" onClick={() => void action("cancel")}>{t("Cancel import")}</button>}
      {job.status === "staged" && <button className="button" disabled={busy} onClick={() => void action("finalize")}>{t("Continue import")}</button>}
      {(job.status === "failed" || job.status === "retry_wait") && job.retryable && <button className="button" disabled={busy} onClick={() => void action("retry")}>{t("Retry import")}</button>}
      {!isImportActive(job) && <button className="button secondary" disabled={busy} onClick={() => void loadReport()}>{t("View import report")}</button>}
      {complete && <Link href="/vault" className="button">{t("Open Vault")}</Link>}
      {report && <><ul>{report.entries.map((entry) => <li key={entry.ordinal}>{entry.path} · {t(entry.status === "failed" ? "Failed" : entry.status === "skipped" ? "Skipped" : entry.status === "published" && complete ? "Imported" : "Unpublished")}{entry.status === "skipped" && entry.skipReason && ` (${t(entry.skipReason === "directory" ? "Folder" : entry.skipReason === "application_configuration" ? "Application configuration" : "Unsupported file format")})`}</li>)}</ul>{report.nextCursor !== null && <button className="button secondary" disabled={busy} onClick={() => void loadReport(report.nextCursor!)}>{t("More files")}</button>}</>}
    </section>}
    {error && <p role="alert" className="error-text">{message(error)}</p>}
  </div>;
}
