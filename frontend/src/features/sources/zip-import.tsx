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

export function ZipImport({ sourceKind }: { sourceKind: ZipSourceKind }) {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<ImportPackage | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<ImportPackageReport | null>(null);
  const upload = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    void dataProvider.listImportPackages().then((list) => {
      if (mounted.current) setJob(list.find((entry) => entry.sourceKind === sourceKind) ?? null);
    }).catch(() => { if (mounted.current) setError("Import history could not be loaded."); });
    return () => { mounted.current = false; upload.current?.abort(); };
  }, [sourceKind]);
  useEffect(() => {
    if (!job || !isImportActive(job) || job.status === "uploading" || job.status === "staged") return;
    let live = true;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void dataProvider.getImportPackage(job.id, controller.signal).then((next) => {
        if (live) { setJob(next); setError(""); }
      }).catch(() => { if (live) setError("Import progress could not be loaded. Refresh to reconnect."); });
    }, 1500);
    return () => { live = false; clearTimeout(timer); controller.abort(); };
  }, [job]);

  function failure(cause: unknown) {
    const status = (cause as { status?: number })?.status;
    return status === 503 ? "ZIP import is unavailable in this environment." : status === 403 ? "Workspace write permission is required." : "Import could not continue. Check the file and try again.";
  }
  async function start() {
    if (!file || busy) return;
    setBusy(true); setError(""); setReport(null);
    const controller = new AbortController(); upload.current = controller;
    try {
      const session = job?.status === "uploading" && job.fileName === file.name && job.fileSize === file.size ? job : await dataProvider.createImportPackage({ sourceKind, fileName: file.name, fileSize: file.size, requestKey: crypto.randomUUID() });
      if (controller.signal.aborted || !mounted.current) return;
      setJob(session);
      await dataProvider.uploadImportPackage(session.id, file, controller.signal);
      if (controller.signal.aborted || !mounted.current) return;
      const next = await dataProvider.importPackageAction(session.id, "finalize");
      if (mounted.current) { setJob(next); setFile(null); }
    } catch (cause) { if (mounted.current && !controller.signal.aborted) setError(failure(cause)); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function action(kind: "cancel" | "retry" | "finalize") {
    if (!job) return;
    if (kind === "cancel") upload.current?.abort();
    setBusy(true); setError("");
    try { const next = await dataProvider.importPackageAction(job.id, kind); if (mounted.current) setJob(next); }
    catch (cause) { if (mounted.current) setError(failure(cause)); }
    finally { if (mounted.current) setBusy(false); }
  }
  async function loadReport(after = -1) {
    if (!job) return;
    setBusy(true); setError("");
    try {
      const next = await dataProvider.getImportPackageReport(job.id, after);
      if (mounted.current) setReport((previous) => ({ ...next, entries: after < 0 ? next.entries : [...(previous?.entries ?? []), ...next.entries] }));
    } catch (cause) { if (mounted.current) setError(failure(cause)); }
    finally { if (mounted.current) setBusy(false); }
  }
  const complete = job && ["completed", "completed_with_skips"].includes(job.status);
  return <div className="capture-form">
    <p className="muted">{t("Import a ZIP snapshot. Markdown, TXT and CSV become sources together after all files are checked. Other files are skipped. Analyze runs only when you choose it.")}</p>
    <label>{t("ZIP export")}<input type="file" accept=".zip,application/zip" disabled={busy || (!!job && isImportActive(job) && job.status !== "uploading")} onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
    <button className="button" disabled={!file || busy || (!!job && isImportActive(job) && job.status !== "uploading")} onClick={() => void start()}>{busy ? t("Working…") : t("Import ZIP")}</button>
    {job && <section aria-label={t("ZIP import progress")}>
      <p role="status">{job.fileName} · {t(importPhaseLabel(job))}</p>
      {job.entryCount !== null && <p>{t("Checked files")}: {job.supportedCount + job.skippedCount} / {job.entryCount} · {t("Supported")}: {job.supportedCount} · {t("Imported")}: {complete ? job.importedCount : 0} · {t("Skipped")}: {job.skippedCount} · {t("Failed")}: {job.status === "failed" ? 1 : 0}</p>}
      {!complete && isImportActive(job) && <p className="muted">{t("Sources stay private until the entire import completes.")}</p>}
      {job.errorCode && <p role="alert">{t("Import stopped")}: <code>{job.errorCode}</code></p>}
      {isImportActive(job) && <button className="button secondary" onClick={() => void action("cancel")}>{t("Cancel import")}</button>}
      {job.status === "staged" && <button className="button" disabled={busy} onClick={() => void action("finalize")}>{t("Continue import")}</button>}
      {job.status === "failed" && job.retryable && <button className="button" disabled={busy} onClick={() => void action("retry")}>{t("Retry import")}</button>}
      {!isImportActive(job) && <button className="button secondary" disabled={busy} onClick={() => void loadReport()}>{t("View import report")}</button>}
      {complete && <Link href="/vault" className="button">{t("Open Vault")}</Link>}
      {report && <><ul>{report.entries.map((entry) => <li key={entry.ordinal}>{entry.path} · {t(entry.status === "skipped" ? "Skipped" : entry.status === "published" && complete ? "Imported" : "Unpublished")}{entry.skipReason && ` (${t(entry.skipReason === "directory" ? "Folder" : entry.skipReason === "application_configuration" ? "Application configuration" : "Unsupported file format")})`}</li>)}</ul>{report.nextCursor !== null && <button className="button secondary" disabled={busy} onClick={() => void loadReport(report.nextCursor!)}>{t("More files")}</button>}</>}
    </section>}
    {error && <p role="alert" className="error-text">{t(error)}</p>}
  </div>;
}
