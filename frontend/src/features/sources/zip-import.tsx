"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { projectHref } from "@/lib/team-context";
import { Dialog } from "@/components/dialog";
import { Icon } from "@/components/icons";
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
  if (["decode_deadline", "inspect_deadline", "job_deadline", "job_resource_limit", "deadline"].includes(code)) return "Import stopped because it took too long. Try a smaller ZIP.";
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
  const [pickerOpen, setPickerOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportFilter, setReportFilter] = useState<"all" | "failed">("failed");
  const [reportBusy, setReportBusy] = useState(false);
  const [pollPaused, setPollPaused] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [checking, setChecking] = useState(false);
  const [cancelPending, setCancelPending] = useState(false);
  const upload = useRef<AbortController | null>(null);
  const reportRequest = useRef<AbortController | null>(null);
  const reportVersion = useRef(0);
  const startButton = useRef<HTMLButtonElement | null>(null);
  const mounted = useRef(true);
  const epoch = useRef(0);
  const actionLock = useRef(false);
  const cancelLock = useRef(false);
  const requestKey = useRef<{ file: File; key: string } | null>(null);
  useEffect(() => {
    mounted.current = true;
    let live = true;
    const controller = new AbortController();
    const initialEpoch = epoch.current;
    void dataProvider.getImportCapabilities(controller.signal).then((value) => {
      if (live) setCapabilities(value);
    }).catch(() => { if (live) setError("Import history could not be loaded."); });
    void dataProvider.listImportPackages(controller.signal).then(async (list) => {
      const recent = list.find((entry) => entry.sourceKind === sourceKind);
      const receipt = recent ? await resolveImportReceipt(recent, list, controller.signal) : null;
      if (live && epoch.current === initialEpoch) { setJob(receipt); setReport(null); }
    }).catch(() => { if (live && epoch.current === initialEpoch) setError("Import history could not be loaded."); });
    return () => { live = false; mounted.current = false; epoch.current += 1; controller.abort(); upload.current?.abort(); reportRequest.current?.abort(); };
  }, [sourceKind]);
  useEffect(() => {
    if (!job || !isImportActive(job) || job.status === "uploading" || job.status === "staged" || busy || pollPaused) return;
    let live = true;
    const pollEpoch = epoch.current;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void dataProvider.getImportPackage(job.id, controller.signal).then((next) => resolveImportReceipt(next, [], controller.signal)).then((next) => {
        if (live && epoch.current === pollEpoch) {
          setJob(next);
          if (!isImportActive(next)) setCancelPending(false);
          setError("");
        }
      }).catch(() => { if (live && epoch.current === pollEpoch) { setError("Import status is unavailable. Check status or try cancelling again."); setPollPaused(true); } });
    }, 1500);
    return () => { live = false; clearTimeout(timer); controller.abort(); };
  }, [job, busy, pollPaused]);

  function failure(cause: unknown) {
    if ((cause as { code?: string })?.code === "import_request_timeout") return "The request timed out. The server may still be processing this import. Check status before retrying.";
    const status = (cause as { status?: number })?.status;
    return status === 503 ? "ZIP import is unavailable in this environment." : status === 403 ? "Workspace write permission is required." : "Import could not continue. Check the file and try again.";
  }
  async function start(selected = file) {
    if (!selected || actionLock.current || !capabilities?.available) return;
    const file = selected;
    if (!file.name.toLowerCase().endsWith(".zip")) { setError("Choose a ZIP file."); return; }
    if (capabilities.maxUploadBytes !== null && file.size > capabilities.maxUploadBytes) { setError("ZIP exceeds this workspace’s configured import limits."); return; }
    actionLock.current = true;
    const operation = ++epoch.current;
    setBusy(true); setPollPaused(false); setCancelPending(false); setJob(null); setError(""); setReport(null); setReportBusy(false); setReportOpen(false); setPickerOpen(false); setDragging(false); setFile(file);
    reportRequest.current?.abort(); reportVersion.current += 1;
    const controller = new AbortController(); upload.current = controller;
    try {
      if (!requestKey.current || requestKey.current.file !== file) requestKey.current = { file, key: crypto.randomUUID() };
      let session = job?.status === "uploading" && job.fileName === file.name && job.fileSize === file.size ? await dataProvider.getImportPackage(job.id, controller.signal) : null;
      if (session && !isImportActive(session)) { requestKey.current = { file, key: crypto.randomUUID() }; session = null; }
      session ??= await dataProvider.createImportPackage({ sourceKind, fileName: file.name, fileSize: file.size, requestKey: requestKey.current.key }, controller.signal);
      if (controller.signal.aborted || !mounted.current || epoch.current !== operation) return;
      setJob(session);
      if (!["uploading", "staged"].includes(session.status)) {
        const receipt = await resolveImportReceipt(session, [], controller.signal);
        if (mounted.current && epoch.current === operation) { setJob(receipt); setFile(null); }
        return;
      }
      if (session.status === "uploading") await dataProvider.uploadImportPackage(session.id, file, controller.signal);
      if (controller.signal.aborted || !mounted.current || epoch.current !== operation) return;
      const next = await resolveImportReceipt(await dataProvider.importPackageAction(session.id, "finalize", controller.signal), [], controller.signal);
      if (mounted.current && epoch.current === operation) { setJob(next); setFile(null); }
    } catch (cause) { if (mounted.current && epoch.current === operation && !controller.signal.aborted) { setError(failure(cause)); setPollPaused(true); } }
    finally { if (mounted.current && epoch.current === operation) { actionLock.current = false; setBusy(false); } }
  }
  async function action(kind: "cancel" | "retry" | "finalize" | "refresh") {
    if (cancelLock.current || (!job && !(kind === "cancel" && file && requestKey.current)) || (actionLock.current && kind !== "cancel")) return;
    const operation = ++epoch.current;
    actionLock.current = true;
    cancelLock.current = kind === "cancel";
    upload.current?.abort();
    const controller = new AbortController(); upload.current = controller;
    setBusy(true); setCancelling(kind === "cancel"); setChecking(kind === "refresh"); setPollPaused(false); setError("");
    if (kind === "cancel") setCancelPending(true);
    let target = job;
    try {
      // A cancelled/uncertain create is recovered with its SAME idempotency key;
      // this branch never uploads or finalizes a package.
      if (!target && file && requestKey.current) {
        target = await dataProvider.createImportPackage({ sourceKind, fileName: file.name, fileSize: file.size, requestKey: requestKey.current.key }, controller.signal);
        if (!mounted.current || epoch.current !== operation) return;
        setJob(target);
      }
      if (!target) return;
      const next = await resolveImportReceipt(await (kind === "refresh" ? dataProvider.getImportPackage(target.id, controller.signal) : dataProvider.importPackageAction(target.id, kind, controller.signal)), [], controller.signal);
      if (mounted.current && epoch.current === operation) {
        setJob(next); setReport(null);
        if (!isImportActive(next)) setCancelPending(false);
        if (kind === "cancel" && isImportActive(next)) { setPollPaused(true); setError("Cancellation is not confirmed. Check status or try cancelling again."); }
        else if (!isImportActive(next)) setFile(null);
      }
    } catch (cause) {
      if (!mounted.current || epoch.current !== operation) return;
      setPollPaused(true);
      setError(kind === "cancel" ? "Cancellation is not confirmed. Check status or try cancelling again." : failure(cause));
      // A response can be lost after the server commits. Read its authoritative
      // result without claiming a local abort cancelled the server operation.
      if (target) {
        try {
          const next = await resolveImportReceipt(await dataProvider.getImportPackage(target.id, controller.signal), [], controller.signal);
          if (mounted.current && epoch.current === operation) {
            setJob(next);
            if (!isImportActive(next)) { setCancelPending(false); setFile(null); setError(""); }
          }
        } catch { /* Keep the last confirmed state and explicit unknown outcome. */ }
      }
    } finally { if (mounted.current && epoch.current === operation) { actionLock.current = false; cancelLock.current = false; setBusy(false); setCancelling(false); setChecking(false); } }
  }
  const complete = !!job && ["completed", "completed_with_skips"].includes(job.status);
  const active = !!job && isImportActive(job);
  const terminal = !!job && !active;
  const checked = job ? Math.min(job.entryCount ?? Infinity, job.supportedCount + job.skippedCount + job.failedCount) : 0;
  const notAdded = job ? (terminal && !complete && job.entryCount !== null ? Math.max(0, job.entryCount - job.importedCount) : job.skippedCount + job.failedCount) : 0;
  const progress = job?.entryCount ? Math.min(100, Math.round(checked / job.entryCount * 100)) : null;
  const animating = (active || busy) && !pollPaused && !cancelling && !checking;
  const disabled = !capabilities?.available || busy || (active && job?.status !== "uploading");
  const reportIssue = (entry: ImportPackageReport["entries"][number]) => !(complete && entry.status === "published");

  async function loadReport(after = -1, filter = reportFilter) {
    if (!job) return;
    const reportEpoch = epoch.current;
    const version = ++reportVersion.current;
    reportRequest.current?.abort();
    const controller = new AbortController(); reportRequest.current = controller;
    setReportBusy(true); setError("");
    try {
      let cursor = after;
      let next: ImportPackageReport;
      const entries: ImportPackageReport["entries"] = [];
      let pages = 0;
      do {
        next = await dataProvider.getImportPackageReport(job.id, cursor, controller.signal);
        entries.push(...next.entries); pages += 1;
        cursor = next.nextCursor ?? -1;
      } while (!controller.signal.aborted && filter === "failed" && !entries.some(reportIssue) && next.nextCursor !== null && pages < 8);
      if (mounted.current && epoch.current === reportEpoch && reportVersion.current === version) setReport((previous) => ({ ...next, entries: after < 0 ? entries : [...(previous?.entries ?? []), ...entries] }));
    } catch (cause) { if (mounted.current && epoch.current === reportEpoch && reportVersion.current === version) setError(failure(cause)); }
    finally { if (mounted.current && epoch.current === reportEpoch && reportVersion.current === version) setReportBusy(false); }
  }
  function openReport(filter: "all" | "failed") {
    setReportFilter(filter); setReportOpen(true); setReport(null);
    void loadReport(-1, filter);
  }
  function chooseFile(selected: File | undefined) {
    if (selected) void start(selected);
  }
  function cancelUpload() {
    void action("cancel");
  }
  function resetResult(chooseAnother = false) {
    if (active || busy) return;
    epoch.current += 1; reportVersion.current += 1;
    upload.current?.abort(); reportRequest.current?.abort(); requestKey.current = null;
    setJob(null); setFile(null); setReport(null); setReportOpen(false); setReportBusy(false);
    setError(""); setCancelPending(false); setPollPaused(false); setPickerOpen(chooseAnother);
    if (!chooseAnother) startButton.current?.focus();
  }
  function closeReport() {
    reportVersion.current += 1; reportRequest.current?.abort(); setReportBusy(false); setReportOpen(false);
  }
  function entryReason(entry: ImportPackageReport["entries"][number]) {
    if (complete && entry.status === "published") return "Added to Vault.";
    if (entry.status === "skipped") return entry.skipReason === "directory" ? "Folder" : entry.skipReason === "application_configuration" ? "Application configuration" : "Unsupported file format";
    if (job?.errorCode) return importErrorLabel(job.errorCode);
    return "This import did not complete. The file was not added.";
  }
  const visibleEntries = report?.entries.filter((entry) => reportFilter === "all" || reportIssue(entry)) ?? [];
  const displayJob = job && !(busy && file && file.name !== job.fileName);
  return <div className="zip-import">
    {capabilities && !capabilities.available && <p role="status" className="muted">{t("ZIP import is unavailable in this environment.")}</p>}
    {((!active || job?.status === "uploading") && !busy) && <button ref={startButton} type="button" className="button zip-import-start" disabled={!capabilities?.available || cancelPending} onClick={() => file && error && !terminal ? void start(file) : setPickerOpen(true)}><Icon name="file" />{file && error && !terminal && !cancelPending ? t("Retry upload") : t("Import ZIP")}</button>}
    {(displayJob || busy) && <section className="zip-progress" aria-label={t("ZIP import progress")}>
      <div className="zip-progress-heading">
        <span className="zip-file-icon"><Icon name="note" /></span>
        <div><strong>{busy && file ? file.name : job?.fileName}</strong><p role="status">{cancelling ? t("Cancelling import…") : checking ? t("Checking import status…") : pollPaused && active ? t("Import status unavailable") : busy && file ? t("Uploading ZIP") : job ? label(importPhaseLabel(job)) : t("Uploading ZIP")}</p></div>
        {complete && !busy && <span className="zip-success" aria-label={t("Import complete")}><Icon name="check" /></span>}
      </div>
      <div className="zip-progress-line">
        <div className={`zip-progress-track ${animating && progress === null ? "is-indeterminate" : !animating ? "is-stopped" : ""}`} role="progressbar" aria-label={t("Checked files")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress ?? undefined} aria-valuetext={progress === null ? terminal && job ? label(importPhaseLabel(job)) : pollPaused ? t("Import status unavailable") : t("Waiting for the file list") : `${checked} / ${job?.entryCount}`}><span style={{ width: progress === null ? animating ? "34%" : "0%" : `${progress}%` }} /></div>
        {progress !== null && <span className="zip-progress-percent">{progress}%</span>}
      </div>
      {job && <div className="zip-stats">
        <div><span>{t("Checked")}</span><strong>{checked} / {job.entryCount ?? "—"}</strong></div>
        <button type="button" disabled={!terminal || reportBusy} onClick={() => openReport("all")}><span>{t("All")}</span><strong>{job.entryCount ?? "—"}</strong></button>
        <button type="button" className={notAdded ? "has-issues" : ""} disabled={!terminal || reportBusy} onClick={() => openReport("failed")}><span>{t("Failed")}</span><strong>{terminal && !complete && job.entryCount === null ? "—" : notAdded}</strong></button>
      </div>}
      {!complete && active && <p className="zip-progress-explanation">{t("Checked files are added together when the import finishes.")}</p>}
      {complete && <p className="zip-progress-explanation">{t("importAddedCount", { count: job!.importedCount })}{notAdded > 0 && ` · ${t("importNotAddedCount", { count: notAdded })}`}</p>}
      {terminal && !complete && <p className="zip-progress-explanation">{t("This import did not complete. The file was not added.")}</p>}
      {job?.errorCode && <p role="alert" className="error-text">{message(importErrorLabel(job.errorCode))}</p>}
      <div className="zip-progress-actions">
        {(active || busy) && <button type="button" className="zip-text-action" disabled={cancelling} onClick={cancelUpload}>{cancelling ? t("Cancelling import…") : cancelPending ? t("Retry cancellation") : t("Cancel import")}</button>}
        {active && pollPaused && <button type="button" className="zip-text-action" disabled={busy} onClick={() => void action("refresh")}>{t("Check status")}</button>}
        {job?.status === "staged" && <button type="button" className="zip-text-action" disabled={busy} onClick={() => void action("finalize")}>{t("Continue import")}</button>}
        {(job?.status === "failed" || job?.status === "retry_wait") && job.retryable && <button type="button" className="zip-text-action" disabled={busy} onClick={() => void action("retry")}>{t("Retry import")}</button>}
        {terminal && <button type="button" className="zip-text-action" disabled={reportBusy} onClick={() => openReport("failed")}><Icon name="note" />{t("View import report")}</button>}
        {terminal && !complete && <button type="button" className="zip-text-action" onClick={() => resetResult(true)}>{t("Choose another ZIP")}</button>}
        {terminal && <button type="button" className="zip-text-action" onClick={() => resetResult()}>{t("Close import")}</button>}
        {complete && <Link href={projectHref("/vault")} className="zip-text-action"><Icon name="vault" />{t("Open Vault")}<span aria-hidden="true">↗</span></Link>}
      </div>
    </section>}
    {error && !pickerOpen && !reportOpen && <p role="alert" className="error-text">{message(error)}</p>}
    {cancelPending && !job && !busy && <button type="button" className="zip-text-action" onClick={cancelUpload}>{t("Retry cancellation")}</button>}
    {pickerOpen && <Dialog title={t("Import ZIP")} onClose={() => { setPickerOpen(false); setDragging(false); }} className="zip-dialog">
      <header className="zip-dialog-header"><div><p className="eyebrow">{label(sourceKind === "notion" ? "Notion" : "Obsidian")}</p><h2>{t("Import your project context")}</h2></div><button type="button" className="icon-button" aria-label={t("Close import window")} onClick={() => setPickerOpen(false)}><Icon name="close" /></button></header>
      <label className={`zip-dropzone ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files.length !== 1) { setError("Choose one ZIP file at a time."); return; } chooseFile(event.dataTransfer.files[0]); }}>
        <span className="zip-drop-icon"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" /></svg></span>
        <strong>{t("Drop ZIP here or")} <span>{t("choose a file")}</span></strong>
        <small>{t("Markdown, TXT and CSV from your ZIP export")}</small>
        <input type="file" accept=".zip,application/zip" aria-label={t("Choose a ZIP file")} disabled={disabled} onChange={(event) => chooseFile(event.target.files?.[0])} />
      </label>
      <p className="zip-dialog-hint">{t("Import starts when you choose a file. Other formats are listed in the report.")}</p>
      {capabilities?.maxUploadBytes && <p className="zip-dialog-limit">{t("zipUploadLimit", { size: Math.round(capabilities.maxUploadBytes / 1_000_000) })}</p>}
      {error && <p role="alert" className="error-text">{message(error)}</p>}
    </Dialog>}
    {reportOpen && <Dialog title={t("Import report")} onClose={closeReport} className="zip-dialog zip-report-dialog">
      <header className="zip-dialog-header"><div><p className="eyebrow">{t("Import report")}</p><h2>{job?.fileName}</h2></div><button type="button" className="icon-button" aria-label={t("Close import window")} onClick={closeReport}><Icon name="close" /></button></header>
      <p className="zip-report-explanation">{t("Failed includes skipped files and files that were not added. Open a file to see why.")}</p>
      <div className="zip-report-filters" role="group" aria-label={t("Filter import report")}><button type="button" aria-pressed={reportFilter === "all"} onClick={() => setReportFilter("all")}>{t("All")}</button><button type="button" aria-pressed={reportFilter === "failed"} onClick={() => { setReportFilter("failed"); if (report && !report.entries.some(reportIssue) && report.nextCursor !== null) void loadReport(report.nextCursor, "failed"); }}>{t("Failed")}</button></div>
      <div className="zip-report-files">{visibleEntries.map((entry) => <details key={entry.ordinal} className="zip-report-file"><summary><Icon name="note" /><span>{entry.path.split("/").at(-1) || entry.path}</span><small>{t(reportIssue(entry) ? "Not added" : "Imported")}</small><Icon name="chevron" /></summary><div><p className="zip-report-path">{entry.path}</p><p>{label(entryReason(entry))}</p></div></details>)}</div>
      {!reportBusy && report && visibleEntries.length === 0 && <p className="zip-report-empty" role="status">{t(report?.nextCursor !== null && report?.nextCursor !== undefined ? "Load more files to finish checking this report." : reportFilter === "failed" && complete && notAdded === 0 ? "All files in this import were added." : "No files in this view.")}</p>}
      {reportBusy && <p role="status" className="muted">{t("Loading import report…")}</p>}
      {report?.nextCursor !== null && report?.nextCursor !== undefined && <button type="button" className="zip-text-action" disabled={reportBusy} onClick={() => void loadReport(report.nextCursor!)}>{t("More files")}</button>}
      {error && <p role="alert" className="error-text">{message(error)}</p>}
    </Dialog>}
  </div>;
}
