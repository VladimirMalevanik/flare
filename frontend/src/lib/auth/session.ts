export interface Session {
  user: {
    id: string;
    email: string;
    name: string;
    emailVerified: boolean;
    legalAccepted: boolean;
  };
  workspace: { id: string; name: string; role: "owner" | "editor" | "viewer" };
}

export class AuthRequestError extends Error {
  constructor(
    message: string,
    readonly code: string | undefined,
    readonly status: number,
  ) {
    super(message);
    this.name = "AuthRequestError";
  }
}

export interface AuthResponse {
  ok: boolean;
  emailVerificationRequired?: boolean;
  message?: string;
}

export const apiBaseUrl = process.env.NEXT_PUBLIC_API_URL ?? "/api";
export const isLocalDemo =
  process.env.NODE_ENV !== "production" &&
  process.env.NEXT_PUBLIC_DATA_PROVIDER === "mock";

export async function authRequest(
  path: string,
  body?: unknown,
): Promise<AuthResponse> {
  const response = await fetch(`${apiBaseUrl}/auth/${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
    cache: "no-store",
  });
  if (!response.ok) {
    const error: unknown = await response.json().catch(() => null);
    const detail =
      typeof error === "object" && error !== null
        ? (error as { detail?: unknown }).detail
        : undefined;
    const structured =
      typeof detail === "object" && detail !== null
        ? (detail as { code?: unknown; message?: unknown })
        : undefined;
    const message =
      typeof structured?.message === "string"
        ? structured.message
        : typeof detail === "string"
          ? detail
          : "Check your details and try again.";
    throw new AuthRequestError(
      message,
      typeof structured?.code === "string" ? structured.code : undefined,
      response.status,
    );
  }
  if (response.status === 204) return { ok: true };
  return response.json() as Promise<AuthResponse>;
}
