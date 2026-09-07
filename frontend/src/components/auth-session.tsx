"use client";
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { apiBaseUrl, type Session } from "@/lib/auth/session";

const Context = createContext<Session | null>(null);
export const useSession = () => useContext(Context);

export function AuthSession({ session, children }: { session: Session | null; children: ReactNode }) {
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
        }
      } catch { /* A transient network error must not destroy the session. */ }
    };
    void check();
    window.addEventListener("focus", check);
    document.addEventListener("visibilitychange", check);
    window.addEventListener("pageshow", check);
    return () => {
      active = false;
      window.removeEventListener("focus", check);
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("pageshow", check);
    };
  }, [session]);
  return <Context.Provider value={session}>{children}</Context.Provider>;
}
