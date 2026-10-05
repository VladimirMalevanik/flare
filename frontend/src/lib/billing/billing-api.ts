export interface BillingStatus {
  environment: "sandbox";
  workspaceId: string;
  plan: "free" | "pro";
  status: string | null;
  canManageBilling: boolean;
  checkoutAvailable: boolean;
  accessUntil: string | null;
  trialEndsAt: string | null;
  currentPeriodEndsAt: string | null;
  scheduledChange: { action: string; effectiveAt: string } | null;
}

export interface CheckoutIntent {
  environment: "sandbox";
  priceId: string;
  quantity: 1;
  email: string;
  customData: { userId: string; checkoutIntent: string };
  expiresAt: string;
}

export type BillingErrorCode = "auth" | "permission" | "configuration" | "backend";

export class BillingRequestError extends Error {
  constructor(readonly code: BillingErrorCode) {
    super("Billing request failed");
    this.name = "BillingRequestError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Only the backend response is authoritative; no local/session plan fallback. */
export function parseBillingStatus(value: unknown): BillingStatus {
  if (!record(value) || value.environment !== "sandbox"
    || typeof value.workspaceId !== "string" || !value.workspaceId
    || (value.plan !== "free" && value.plan !== "pro")
    || !(value.status === null || typeof value.status === "string")
    || typeof value.canManageBilling !== "boolean" || typeof value.checkoutAvailable !== "boolean"
    || (value.plan === "pro" && (typeof value.accessUntil !== "string" || !Number.isFinite(Date.parse(value.accessUntil))))
    || ![value.accessUntil, value.trialEndsAt, value.currentPeriodEndsAt].every((date) => date === null || typeof date === "string")
    || !(value.scheduledChange === null || (record(value.scheduledChange)
      && typeof value.scheduledChange.action === "string" && typeof value.scheduledChange.effectiveAt === "string"))) {
    throw new BillingRequestError("backend");
  }
  return {
    environment: "sandbox", workspaceId: value.workspaceId, plan: value.plan,
    status: value.status, canManageBilling: value.canManageBilling,
    checkoutAvailable: value.checkoutAvailable,
    accessUntil: value.accessUntil as string | null,
    trialEndsAt: value.trialEndsAt as string | null,
    currentPeriodEndsAt: value.currentPeriodEndsAt as string | null,
    scheduledChange: value.scheduledChange as BillingStatus["scheduledChange"],
  };
}

export function parseCheckoutIntent(value: unknown): CheckoutIntent {
  if (!record(value) || value.environment !== "sandbox"
    || typeof value.priceId !== "string" || value.quantity !== 1
    || typeof value.email !== "string" || !record(value.customData)
    || typeof value.customData.userId !== "string" || !value.customData.userId
    || typeof value.customData.checkoutIntent !== "string" || !value.customData.checkoutIntent
    || typeof value.expiresAt !== "string") {
    throw new BillingRequestError("backend");
  }
  return {
    environment: "sandbox", priceId: value.priceId, quantity: 1, email: value.email,
    customData: { userId: value.customData.userId, checkoutIntent: value.customData.checkoutIntent },
    expiresAt: value.expiresAt,
  };
}

export function createBillingApi({
  baseUrl,
  request = fetch,
}: { baseUrl: string; request?: typeof fetch }) {
  async function call(path: string, method: "GET" | "POST", signal: AbortSignal) {
    const response = await request(`${baseUrl}/billing/${path}`, {
      method, credentials: "include", cache: "no-store", signal,
      ...(method === "POST" ? { headers: { "Content-Type": "application/json" }, body: "{}" } : {}),
    });
    if (!response.ok) {
      const detail: unknown = await response.json().catch(() => null);
      const code = record(detail) && record(detail.detail) ? detail.detail.code : undefined;
      throw new BillingRequestError(response.status === 401 ? "auth"
        : response.status === 403 ? "permission"
        : code === "billing_not_configured" ? "configuration"
        : "backend");
    }
    return response.json() as Promise<unknown>;
  }
  return {
    getStatus: async (signal: AbortSignal) => parseBillingStatus(await call("status", "GET", signal)),
    createCheckoutIntent: async (signal: AbortSignal) => parseCheckoutIntent(await call("checkout-intents", "POST", signal)),
  };
}
