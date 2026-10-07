import "server-only";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { Session } from "./session";
import { isLocalDemo } from "./session";

type SessionResult =
  | { kind: "anonymous" }
  | { kind: "membership-required" }
  | { kind: "authenticated"; session: Session };

async function readSession(): Promise<SessionResult> {
  const incoming = await headers();
  const cookie = incoming.get("cookie") ?? "";
  // Guests can use the public site even while the API is unavailable.
  if (!/(?:^|;\s*)(?:__Host-flare_session|flare_session)=/.test(cookie)) {
    return { kind: "anonymous" };
  }
  const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/auth/me`, {
    headers: { Cookie: cookie },
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  if (response.status === 401) return { kind: "anonymous" };
  if (response.status === 403) return { kind: "membership-required" };
  if (!response.ok) throw new Error("Authentication service is unavailable. Please retry.");
  return { kind: "authenticated", session: (await response.json()) as Session };
}

function requireAccountChecks(session: Session): void {
  if (!session.user.emailVerified) redirect("/verify-email?pending=1");
  if (!session.user.legalAccepted) redirect("/legal-acceptance");
}

export async function requireSession(): Promise<Session | null> {
  if (isLocalDemo) return null;
  const result = await readSession();
  if (result.kind === "anonymous") redirect("/login");
  if (result.kind === "membership-required") redirect("/login?reason=membership");
  requireAccountChecks(result.session);
  return result.session;
}

/** Return signed-in visitors to their account before showing public entry forms. */
export async function redirectSignedInUser(): Promise<void> {
  if (isLocalDemo) return;
  const result = await readSession();
  // A missing membership must not loop between the entry page and Vault.
  if (result.kind !== "authenticated") return;
  requireAccountChecks(result.session);
  redirect("/vault");
}
