import "server-only";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import type { Session } from "./session";
import { isLocalDemo } from "./session";

export async function requireSession(): Promise<Session | null> {
  if (isLocalDemo) return null;
  const incoming = await headers();
  const response = await fetch(`${process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"}/auth/me`, {
    headers: { Cookie: incoming.get("cookie") ?? "" },
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
  });
  if (response.status === 401) redirect("/login");
  if (response.status === 403) redirect("/login?reason=membership");
  if (!response.ok) throw new Error("Authentication service is unavailable. Please retry.");
  const session = (await response.json()) as Session;
  if (!session.user.emailVerified) redirect("/verify-email?pending=1");
  return session;
}
