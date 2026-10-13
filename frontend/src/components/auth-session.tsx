"use client";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiBaseUrl, type Session } from "@/lib/auth/session";
import { useI18n } from "@/i18n/provider";
import { selectedProject } from "@/lib/team-context";
import { teamRequest, type ProjectsResponse } from "@/features/team/api";

const Context = createContext<Session | null>(null);
export const useSession = () => useContext(Context);

export function AuthSession({ session, children }: { session: Session | null; children: ReactNode }) {
  const { locale } = useI18n();
  const copy = (en: string, es: string) => locale === "es" ? es : en;
  const [selected, setSelected] = useState<Session | null | undefined>(undefined);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    async function load() {
      try {
        const invitation = JSON.parse(sessionStorage.getItem("flare-team-invitation") ?? "null");
        if (session && invitation?.expires > Date.now() && /^[A-Za-z0-9_-]{43}$/.test(invitation.token)) {
          window.location.replace("/join"); return;
        }
      } catch { /* Private storage may be unavailable; invitation email still works. */ }
      const project = selectedProject();
      if (!session || !project || project === session.workspace.id) { if (live) setSelected(session); return; }
      try {
        const result = await teamRequest<ProjectsResponse>("/projects",undefined,undefined,controller.signal);
        const workspace = result.projects.find(p => p.id === project);
        if (!workspace) throw new Error("This project is unavailable for your account.");
        if (live) setSelected({ ...session, workspace:{id:workspace.id,name:workspace.name,role:workspace.role} });
      } catch (cause) { if (live) setError(cause instanceof Error ? cause.message : "Could not open this project."); }
    }
    void load();
    return () => { live = false; controller.abort(); };
  }, [session]);
  useEffect(() => {
    if (!session) return;
    let active = true;
    const check = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const response = await fetch(`${apiBaseUrl}/auth/me`, { credentials: "include", cache: "no-store" });
        if (active && (response.status === 401 || response.status === 403)) window.location.replace("/login");
        else if (response.ok) {
          const current: Session = await response.json();
          if (active && (current.user.id !== session.user.id || current.workspace.id !== session.workspace.id)) window.location.reload();
          else if (active && selectedProject()) {
            const result = await teamRequest<ProjectsResponse>("/projects");
            const workspace = result.projects.find(p => p.id === selectedProject());
            if (active && !workspace) setError("Your access to this project has ended.");
            else if (active && workspace) setSelected({ ...current,workspace:{id:workspace.id,name:workspace.name,role:workspace.role} });
          }
        }
      } catch { /* A transient network error must not destroy the session. */ }
    };
    void check();
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    window.addEventListener("pageshow", check);
    window.addEventListener("flare:team-refresh", check);
    return () => {
      active = false;
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("pageshow", check);
      window.removeEventListener("flare:team-refresh", check);
    };
  }, [session]);
  if (error) return <main className="page"><h1>{copy("Project unavailable","Proyecto no disponible")}</h1><p role="alert">{error}</p><a className="button primary" href="/vault">{copy("Return to personal project","Volver al proyecto personal")}</a></main>;
  if (selected === undefined && session) return <main className="page" aria-busy="true"><p role="status">{copy("Opening your project…","Abriendo tu proyecto…")}</p></main>;
  return <Context.Provider value={selected ?? session}>{children}</Context.Provider>;
}
