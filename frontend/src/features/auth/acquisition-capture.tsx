"use client";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { apiBaseUrl } from "@/lib/auth/session";
import { acquisitionChoice, acquisitionPrivacyBlocked, captureAcquisition, chooseAcquisition, withdrawAcquisition } from "@/lib/auth/acquisition";
import { useAcquisitionPolicy } from "@/features/acquisition/use-policy";
import { acquisitionCopy } from "@/features/acquisition/copy";
import { useI18n } from "@/i18n/provider";
import { siteAnalytics } from "@/lib/telemetry/client";
import styles from "@/features/telemetry/telemetry.module.css";

export function AcquisitionCapture() {
  const pathname = usePathname();
  const query = useSearchParams().toString();
  const publicRoute = ["/", "/login", "/register"].includes(pathname);
  const routeKey = `${pathname}?${query}`;
  const policy = useAcquisitionPolicy(routeKey);
  const { locale } = useI18n();
  const copy = acquisitionCopy[locale];
  const azure = useSyncExternalStore(siteAnalytics.subscribe, siteAnalytics.getSnapshot, siteAnalytics.getServerSnapshot);
  const [decision, setDecision] = useState<{ key: string; hidden: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!publicRoute || !policy) return;
    if (acquisitionPrivacyBlocked()) {
      void withdrawAcquisition(apiBaseUrl);
    } else if (acquisitionChoice(policy) === "allowed") {
      void captureAcquisition(apiBaseUrl, policy);
    }
  }, [publicRoute, policy]);
  // Independent choices share the existing notice style and appear in sequence,
  // so they never overlap on a narrow screen or reuse Azure's consent.
  if (!publicRoute || !policy || acquisitionPrivacyBlocked() ||
      acquisitionChoice(policy) !== "unset" || (decision?.key === routeKey && decision.hidden) ||
      (azure.configured && !azure.privacyBlocked && (azure.choice === "unset" || azure.storageError))) return null;
  async function choose(allowed: boolean) {
    if (!policy || busy) return;
    setBusy(true); setError(false);
    const saved = chooseAcquisition(policy, allowed);
    if (saved && allowed) await captureAcquisition(apiBaseUrl, policy);
    if (!allowed) await withdrawAcquisition(apiBaseUrl);
    setError(!saved);
    setDecision({ key: routeKey, hidden: saved });
    setBusy(false);
  }
  return <section className={styles.banner} aria-labelledby="acquisition-consent-title">
    <h2 id="acquisition-consent-title" className={styles.title}>{copy.title}</h2>
    <p className={styles.description}>{copy.description}</p>
    <div className={styles.actions}>
      <button type="button" className={styles.button} disabled={busy} onClick={() => void choose(true)}>{busy ? copy.busy : copy.allow}</button>
      <button type="button" className={styles.button} disabled={busy} onClick={() => void choose(false)}>{copy.reject}</button>
      <Link className={styles.link} href="/measurement">{copy.details}</Link>
    </div>
    {error && <p className={`${styles.note} ${styles.error}`} role="status">{copy.error}</p>}
  </section>;
}
