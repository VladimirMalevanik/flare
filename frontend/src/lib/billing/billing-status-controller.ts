import { BillingRequestError, type BillingStatus } from "./billing-api";

export interface BillingSnapshot {
  phase: "loading" | "ready" | "error";
  status: BillingStatus | null;
  error: "auth" | "configuration" | "backend" | null;
  pendingConfirmation: boolean;
  confirmationTimedOut: boolean;
}

const initial: BillingSnapshot = Object.freeze({
  phase: "loading", status: null, error: null, pendingConfirmation: false, confirmationTimedOut: false,
});

export function hasUnexpiredProAccess(status: BillingStatus, now = Date.now()): boolean {
  return typeof status.accessUntil === "string" && Number.isFinite(Date.parse(status.accessUntil))
    && Date.parse(status.accessUntil) > now;
}

/** Shared authoritative status with bounded confirmation polling and identity fencing. */
export function createBillingStatusClient({
  load,
  requestTimeoutMs = 8_000,
  pollIntervalMs = 2_000,
  confirmationTimeoutMs = 30_000,
  now = () => Date.now(),
}: {
  load: (signal: AbortSignal) => Promise<BillingStatus>;
  requestTimeoutMs?: number;
  pollIntervalMs?: number;
  confirmationTimeoutMs?: number;
  now?: () => number;
}) {
  let snapshot = initial;
  let workspaceId: string | undefined;
  let generation = 0;
  let lastCompletion = 0;
  let active = false;
  let abort: AbortController | undefined;
  let inFlight: Promise<void> | undefined;
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  let expiryTimer: ReturnType<typeof setTimeout> | undefined;
  const listeners = new Set<() => void>();

  function publish(next: BillingSnapshot) {
    snapshot = next;
    listeners.forEach((listener) => listener());
  }
  function clearPolling() {
    if (pollTimer !== undefined) clearTimeout(pollTimer);
    if (deadline !== undefined) clearTimeout(deadline);
    pollTimer = deadline = undefined;
  }
  function clearExpiry() {
    if (expiryTimer !== undefined) clearTimeout(expiryTimer);
    expiryTimer = undefined;
  }
  function scheduleExpiry(status: BillingStatus) {
    clearExpiry();
    if (status.plan !== "pro" || !status.accessUntil) return;
    const expiresAt = Date.parse(status.accessUntil);
    const attempt = generation;
    const schedule = () => {
      // Browsers cap timeouts at ~24 days; a 30-day trial must not overflow.
      expiryTimer = setTimeout(() => {
        expiryTimer = undefined;
        if (!active || attempt !== generation || snapshot.status !== status) return;
        if (now() < expiresAt) return schedule();
        publish({ ...snapshot, phase: "loading", status: null, error: null });
        void refresh();
      }, Math.min(Math.max(0, expiresAt - now()), 2_147_483_647));
    };
    schedule();
  }
  function stop() {
    active = false;
    generation += 1;
    clearPolling();
    clearExpiry();
    abort?.abort();
    abort = undefined;
    inFlight = undefined;
  }
  async function refresh() {
    if (!active) return;
    if (snapshot.status?.plan === "pro" && !hasUnexpiredProAccess(snapshot.status, now())) {
      clearExpiry();
      publish({ ...snapshot, phase: "loading", status: null, error: null });
    }
    if (inFlight) return inFlight;
    const attempt = generation;
    const controller = new AbortController();
    abort = controller;
    publish({ ...snapshot, phase: "loading", error: null });
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const pending = (async () => {
      try {
        const value = await Promise.race([
          Promise.resolve().then(() => load(controller.signal)),
          new Promise<never>((_, reject) => {
            controller.signal.addEventListener("abort", () => reject(new BillingRequestError("backend")), { once: true });
            timeout = setTimeout(() => {
              reject(new BillingRequestError("backend"));
              controller.abort();
            }, requestTimeoutMs);
          }),
        ]);
        if (!active || attempt !== generation || controller.signal.aborted) return;
        if (value.workspaceId !== workspaceId || (value.plan === "pro" && !hasUnexpiredProAccess(value, now()))) {
          throw new BillingRequestError("backend");
        }
        clearExpiry();
        publish({ ...snapshot, phase: "ready", status: value, error: null });
        scheduleExpiry(value);
        if (value.plan === "pro") {
          clearPolling();
          publish({ ...snapshot, pendingConfirmation: false, confirmationTimedOut: false });
        }
      } catch (error) {
        if (!active || attempt !== generation) return;
        const code = error instanceof BillingRequestError ? error.code : "backend";
        if (snapshot.status?.plan === "pro" && !hasUnexpiredProAccess(snapshot.status, now())) {
          clearExpiry();
          publish({ ...snapshot, status: null });
        }
        publish({ ...snapshot, phase: "error", error: code === "auth" || code === "permission" ? "auth"
          : code === "configuration" ? "configuration" : "backend" });
      } finally {
        if (timeout !== undefined) clearTimeout(timeout);
        if (attempt === generation && abort === controller) {
          abort = undefined;
          inFlight = undefined;
        }
      }
    })();
    inFlight = pending;
    return pending;
  }
  async function poll(attempt: number) {
    await refresh();
    if (!active || attempt !== generation || !snapshot.pendingConfirmation) return;
    if (snapshot.error === "auth" || snapshot.error === "configuration") {
      clearPolling();
      publish({ ...snapshot, pendingConfirmation: false });
      return;
    }
    pollTimer = setTimeout(() => void poll(attempt), pollIntervalMs);
  }

  return {
    getSnapshot: () => snapshot,
    getServerSnapshot: () => initial,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    start(identity: { userId: string; workspaceId: string } | null, baselineCompletion = 0) {
      stop();
      snapshot = initial;
      // Historical completions belong to the previous route/account lifecycle.
      // The mount GET already resolves their authoritative subscription status.
      lastCompletion = baselineCompletion;
      workspaceId = identity?.workspaceId;
      if (!identity) {
        publish({ ...initial, phase: "error", error: "auth" });
        return;
      }
      active = true;
      publish(initial);
      void refresh();
    },
    stop,
    refresh,
    checkAgain() {
      publish({ ...snapshot, confirmationTimedOut: false });
      return refresh();
    },
    confirmCheckout(completion: number) {
      if (!active || completion <= lastCompletion || completion <= 0) return;
      lastCompletion = completion;
      if (snapshot.status?.plan === "pro" && hasUnexpiredProAccess(snapshot.status, now())) return;
      clearPolling();
      publish({ ...snapshot, pendingConfirmation: true, confirmationTimedOut: false });
      const attempt = generation;
      deadline = setTimeout(() => {
        if (!active || attempt !== generation) return;
        clearPolling();
        publish({ ...snapshot, pendingConfirmation: false, confirmationTimedOut: true });
      }, confirmationTimeoutMs);
      void poll(attempt);
    },
  };
}
