"use client";

import { useEffect } from "react";
import { apiBaseUrl, isLocalDemo, type Session } from "@/lib/auth/session";

/** Recheck public entry pages that a browser restores without a server render. */
export function AuthEntrySession() {
  useEffect(() => {
    if (isLocalDemo) return;
    let active = true;
    let navigating = false;
    let pending: AbortController | null = null;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    const check = async () => {
      if (!active || navigating || pending || document.visibilityState !== "visible") return;
      const controller = new AbortController();
      pending = controller;
      const deadline = setTimeout(() => {
        controller.abort();
        if (pending === controller) pending = null;
      }, 10_000);
      timeout = deadline;
      try {
        const response = await fetch(`${apiBaseUrl}/auth/me`, {
          credentials: "include",
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) return;
        const current: Session | null = await response.json();
        if (!active || controller.signal.aborted || navigating ||
            typeof current?.user?.id !== "string" || !current.user.id ||
            typeof current?.workspace?.id !== "string" || !current.workspace.id ||
            typeof current.user.emailVerified !== "boolean" ||
            typeof current.user.legalAccepted !== "boolean") return;
        const destination = !current.user.emailVerified ? "/verify-email?pending=1"
          : !current.user.legalAccepted ? "/legal-acceptance" : "/vault";
        navigating = true;
        window.location.replace(destination);
      } catch {
        // An unavailable service must leave the form usable, without changing the session.
      } finally {
        clearTimeout(deadline);
        if (pending === controller) {
          pending = null;
          timeout = undefined;
        }
      }
    };

    void check();
    window.addEventListener("focus", check);
    window.addEventListener("pageshow", check);
    document.addEventListener("visibilitychange", check);
    return () => {
      active = false;
      pending?.abort();
      clearTimeout(timeout);
      window.removeEventListener("focus", check);
      window.removeEventListener("pageshow", check);
      document.removeEventListener("visibilitychange", check);
    };
  }, []);
  return null;
}
