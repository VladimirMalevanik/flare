"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import { apiBaseUrl } from "@/lib/auth/session";
import { acquisitionPolicy, acquisitionPrivacyBlocked, type AcquisitionPolicy } from "@/lib/auth/acquisition";

function subscribePrivacy(listener: () => void) {
  window.addEventListener("focus", listener);
  window.addEventListener("pageshow", listener);
  return () => { window.removeEventListener("focus", listener); window.removeEventListener("pageshow", listener); };
}
export function useAcquisitionPrivacy() {
  return useSyncExternalStore(subscribePrivacy, acquisitionPrivacyBlocked, () => false);
}

export function useAcquisitionPolicy(routeKey: string) {
  const [loaded, setLoaded] = useState<{ key: string; policy: AcquisitionPolicy | null } | null>(null);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 1000);
    void acquisitionPolicy(apiBaseUrl, controller.signal).then(policy => {
      if (live) setLoaded({ key: routeKey, policy });
    });
    return () => { live = false; controller.abort(); window.clearTimeout(timer); };
  }, [routeKey]);
  return loaded?.key === routeKey ? loaded.policy : null;
}
