import type { InitializePaddleOptions, Paddle, PaddleEventData } from "@paddle/paddle-js";

export type CheckoutErrorCode = "configuration" | "sandbox-only" | "price" | "auth" | "load" | "open" | "payment";
export interface CheckoutSnapshot {
  phase: "idle" | "loading" | "open" | "complete";
  error: CheckoutErrorCode | null;
}
export interface CheckoutUser { id: string; email: string }
type CheckoutPaddle = Pick<Paddle, "Initialized" | "Checkout">;

const idleSnapshot: CheckoutSnapshot = Object.freeze({ phase: "idle", error: null });

/** One controller per page, shared across renders and route transitions. */
export function createSandboxCheckoutClient({
  token,
  proPriceId,
  initialize,
  getTheme = () => "light",
  loadTimeoutMs = 15_000,
  openTimeoutMs = 20_000,
}: {
  token: string | undefined;
  proPriceId: string | undefined;
  initialize: (options: InitializePaddleOptions) => Promise<CheckoutPaddle | undefined>;
  getTheme?: () => "light" | "dark";
  loadTimeoutMs?: number;
  openTimeoutMs?: number;
}) {
  let snapshot = idleSnapshot;
  let initialization: Promise<CheckoutPaddle | undefined> | undefined;
  let paddle: CheckoutPaddle | undefined;
  let overlayRequested = false;
  let generation = 0;
  let openingTimer: ReturnType<typeof setTimeout> | undefined;
  const listeners = new Set<() => void>();

  function publish(next: CheckoutSnapshot) {
    snapshot = next;
    listeners.forEach((listener) => listener());
  }
  function clearOpeningTimer() {
    if (openingTimer !== undefined) clearTimeout(openingTimer);
    openingTimer = undefined;
  }
  function fail(error: CheckoutErrorCode) {
    clearOpeningTimer();
    // Ignore the close event caused by our own cleanup, preserving the error.
    const shouldClose = overlayRequested;
    overlayRequested = false;
    if (shouldClose) {
      try { paddle?.Checkout.close(); } catch { /* Still release the local lock. */ }
    }
    publish({ phase: "idle", error });
  }
  function onEvent(event: PaddleEventData) {
    if (!overlayRequested) return;
    // Only event names are consumed. Payment/customer data is never logged or stored.
    switch (event.name) {
      case "checkout.loaded":
        clearOpeningTimer();
        publish({ phase: "open", error: null });
        break;
      case "checkout.completed":
        clearOpeningTimer();
        publish({ phase: "complete", error: null });
        // The success overlay stays open. Keep the lock until checkout.closed.
        break;
      case "checkout.closed":
        clearOpeningTimer();
        overlayRequested = false;
        publish(idleSnapshot);
        break;
      case "checkout.error":
      case "checkout.failed":
        fail("open");
        break;
      case "checkout.payment.failed":
      case "checkout.payment.error":
        clearOpeningTimer();
        publish({ phase: "open", error: "payment" });
        break;
    }
  }

  async function loadPaddle(clientToken: string) {
    // Do not reinitialize after rendering, navigating, closing, or an SDK failure.
    initialization ??= Promise.resolve().then(() => initialize({
      environment: "sandbox",
      token: clientToken,
      eventCallback: onEvent,
    }));
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        initialization,
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error("Paddle load timeout")), loadTimeoutMs);
        }),
      ]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
    }
  }

  return {
    getSnapshot: () => snapshot,
    getServerSnapshot: () => idleSnapshot,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    cancelPendingCheckout() {
      if (snapshot.phase !== "loading") return;
      generation += 1;
      clearOpeningTimer();
      const shouldClose = overlayRequested;
      overlayRequested = false;
      if (shouldClose) {
        try { paddle?.Checkout.close(); } catch { /* The pending attempt is cancelled locally. */ }
      }
      publish(idleSnapshot);
    },
    async openProCheckout(user: CheckoutUser | null, locale: "en" | "es") {
      // Synchronous lock, before the first await, including the success overlay.
      if (snapshot.phase !== "idle") return;
      const clientToken = token?.trim();
      const priceId = proPriceId?.trim();
      if (!clientToken || !priceId) return fail("configuration");
      if (!/^test_[A-Za-z0-9_-]+$/.test(clientToken)) return fail("sandbox-only");
      if (!/^pri_[a-z0-9]{26}$/.test(priceId)) return fail("price");
      if (typeof user?.id !== "string" || !user.id.trim()
        || typeof user.email !== "string" || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(user.email)) return fail("auth");

      const attempt = ++generation;
      publish({ phase: "loading", error: null });
      try {
        const loaded = await loadPaddle(clientToken);
        if (attempt !== generation) return;
        paddle = loaded;
        // The official wrapper can resolve undefined or an uninitialized instance.
        if (!paddle?.Initialized) return fail("load");
      } catch {
        if (attempt !== generation) return;
        return fail("load");
      }
      try {
        overlayRequested = true;
        openingTimer = setTimeout(() => {
          if (attempt === generation) fail("open");
        }, openTimeoutMs);
        paddle.Checkout.open({
          items: [{ priceId, quantity: 1 }],
          customer: { email: user.email },
          customData: { userId: user.id },
          settings: {
            displayMode: "overlay",
            allowLogout: false,
            locale,
            theme: getTheme(),
          },
        });
      } catch {
        fail("open");
      }
    },
  };
}
