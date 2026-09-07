export interface Session {
  user: { id: string; email: string; name: string };
  workspace: { id: string; name: string; role: "owner" | "editor" | "viewer" };
}

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "/api";
export const isLocalDemo =
  process.env.NODE_ENV !== "production" &&
  process.env.NEXT_PUBLIC_DATA_PROVIDER === "mock";

export async function authRequest(path: string, body?: unknown): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/auth/${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
    cache: "no-store",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === "string" ? error.detail : "Check your details and try again.");
  }
}
