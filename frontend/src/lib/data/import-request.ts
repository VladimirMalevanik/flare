export const IMPORT_REQUEST_MS = 15_000;
export const IMPORT_UPLOAD_MS = 120_000;

export class ImportRequestError extends Error {
  constructor(readonly code: "import_request_timeout" | "import_request_aborted") {
    super(code);
    this.name = "ImportRequestError";
  }
}

/** Bound the whole request, including response parsing, even if abort is ignored. */
export function importRequest<T>(run: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal,
  timeoutMs = IMPORT_REQUEST_MS): Promise<T> {
  if (signal?.aborted) return Promise.reject(new ImportRequestError("import_request_aborted"));
  return new Promise<T>((resolve, reject) => {
    const controller = new AbortController();
    let settled = false;
    const finish = (action: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      action();
    };
    const stop = (code: "import_request_timeout" | "import_request_aborted") => {
      finish(() => { controller.abort(); reject(new ImportRequestError(code)); });
    };
    const abort = () => stop("import_request_aborted");
    const timer = setTimeout(() => stop("import_request_timeout"), timeoutMs);
    signal?.addEventListener("abort", abort, { once: true });
    // Defer invocation so both synchronous errors and ignored/late responses settle safely.
    Promise.resolve().then(() => {
      if (controller.signal.aborted) throw new ImportRequestError("import_request_aborted");
      return run(controller.signal);
    }).then((value) => finish(() => resolve(value)), (cause) => finish(() => reject(cause)));
  });
}
