import type { ImportPackage, ZipSourceKind } from "@/lib/data";

const terminalStatuses = new Set(["completed", "completed_with_skips", "failed", "cancelled", "expired"]);

export function importDismissalKey(userId: string, workspaceId: string, sourceKind: ZipSourceKind): string {
  return `flare-zip-dismissed-v1:${JSON.stringify([userId, workspaceId, sourceKind])}`;
}

function receiptFingerprint(requestId: string, job: ImportPackage): string {
  // Keep the request identity as well as the canonical result: a new upload of
  // the same ZIP must still show its own receipt. No names or content are stored.
  return JSON.stringify([requestId, job.id, job.status, job.phase, job.errorCode,
    job.entryCount, job.supportedCount, job.importedCount, job.skippedCount, job.failedCount, job.chunkCount, job.retryable]);
}

export function wasImportDismissed(key: string | null, requestId: string, job: ImportPackage): boolean {
  if (!key || !terminalStatuses.has(job.status) || typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(key) === receiptFingerprint(requestId, job);
  } catch {
    return false;
  }
}

export function dismissImport(key: string | null, requestId: string, job: ImportPackage): boolean {
  if (!key || !terminalStatuses.has(job.status) || typeof window === "undefined") return false;
  try {
    const fingerprint = receiptFingerprint(requestId, job);
    window.localStorage.setItem(key, fingerprint);
    return window.localStorage.getItem(key) === fingerprint;
  } catch {
    return false;
  }
}
