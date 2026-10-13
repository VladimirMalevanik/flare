import { apiBaseUrl } from "@/lib/auth/session";
import { importRequest, ImportRequestError } from "@/lib/data/import-request";

export type TeamRole = "owner" | "editor" | "viewer";
export type Project = { id: string; name: string; role: TeamRole; kind: "personal" | "team" | "shared"; writable: boolean; canManageLicense: boolean };
export type Capability = { enabled: boolean; canCreate: boolean; requiresVerification: boolean; projectCount: number;
  limits: { projects: number; members: number; documents: number; contentBytes: number; invitationsDaily: number } };
export type ProjectsResponse = { projects: Project[]; capability: Capability };
export type Member = { id: string; name: string; email: string | null; role: TeamRole };
export type Invitation = { id: string; email: string; role: "editor" | "viewer"; status: "pending" | "accepted" | "canceled" | "expired"; expiresAt: string };

export class TeamError extends Error {
  constructor(message: string, readonly status: number, readonly code: string | undefined) { super(message); }
}

export async function teamRequest<T>(path: string, body?: unknown, method?: string, signal?: AbortSignal): Promise<T> {
  try {
    return await importRequest(async boundedSignal => {
  const response = await fetch(`${apiBaseUrl}/team${path}`, { method: method ?? (body === undefined ? "GET" : "POST"),
    credentials: "include", cache: "no-store", signal: boundedSignal,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }) });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new TeamError(typeof payload?.detail?.message === "string" ? payload.detail.message : "This action could not complete. Please retry.",response.status,payload?.detail?.code);
  }
  return response.status === 204 ? undefined as T : await response.json() as T;
    },signal,12_000);
  } catch (cause) {
    if (cause instanceof ImportRequestError) throw new TeamError("This request stopped. Keep your draft and check the latest status before retrying.",408,"team_request_stopped");
    throw cause;
  }
}
