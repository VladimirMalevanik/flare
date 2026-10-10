import { apiBaseUrl } from "@/lib/auth/session";

export type MailCapability = { allowed: boolean; ready?: boolean; sender?: string | null; maxRecipients?: number };
export type MailOutcome = { recipient: string; status: "accepted" | "failed" | "unknown" };
export type MailDraft = { recipients: string; subject: string; body: string };
export class MailRequestError extends Error {
  constructor(public readonly uncertain: boolean) { super("Manual email request failed"); }
}
const mailbox = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$/;

export function parseRecipients(value: string): string[] {
  const addresses = value.split(/[,;\n\r]+/).map(value => value.trim()).filter(Boolean);
  if (!addresses.length || addresses.length > 20 || addresses.some(address => {
    const [local, domain = ""] = address.split("@");
    return address.length > 254 || !mailbox.test(address) || local.length > 64 ||
      local.startsWith(".") || local.endsWith(".") || local.includes("..") ||
      domain.split(".").some(label => label.length > 63);
  })) throw new Error("recipients");
  return [...new Map(addresses.map(address => [address.toLowerCase(), address])).values()];
}

export async function mailCapability(signal: AbortSignal): Promise<MailCapability> {
  const response = await fetch(`${apiBaseUrl}/ops/mail/capability`, {
    credentials: "include", cache: "no-store", signal,
  });
  if (!response.ok) return { allowed: false };
  const value = await response.json();
  if (value.allowed !== true) return { allowed: false };
  return { allowed: true, ready: value.ready === true, sender: typeof value.sender === "string" ? value.sender : null };
}

export async function sendMail(recipients: string[], draft: MailDraft): Promise<MailOutcome[]> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 90_000);
  try {
    const response = await fetch(`${apiBaseUrl}/ops/mail/send`, {
      method: "POST", credentials: "include", cache: "no-store", signal: controller.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipients, subject: draft.subject, body: draft.body }),
    });
    if (!response.ok) throw new MailRequestError(![400, 401, 403, 422, 503].includes(response.status));
    const result: unknown = await response.json();
    if (!Array.isArray(result) || result.length !== recipients.length || result.some((item, index) =>
      item?.recipient !== recipients[index] || !["accepted", "failed", "unknown"].includes(item?.status))) {
      throw new MailRequestError(true);
    }
    return result as MailOutcome[];
  } catch (error) {
    throw error instanceof MailRequestError ? error : new MailRequestError(true);
  } finally { clearTimeout(timer); }
}
