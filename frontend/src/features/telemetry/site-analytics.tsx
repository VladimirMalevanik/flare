"use client";
import Link from "next/link";
import { useEffect, useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { useI18n } from "@/i18n/provider";
import { CONSENT_KEY, siteAnalytics } from "@/lib/telemetry/client";
import { telemetryCopy } from "./copy";
import styles from "./telemetry.module.css";

export function SiteAnalytics() {
  const pathname = usePathname();
  const { locale } = useI18n();
  const copy = telemetryCopy[locale];
  const snapshot = useSyncExternalStore(siteAnalytics.subscribe, siteAnalytics.getSnapshot, siteAnalytics.getServerSnapshot);
  useEffect(() => {
    siteAnalytics.initialize();
    const refresh = () => { if (document.visibilityState === "visible") siteAnalytics.reconcile(); };
    const storage = (event: StorageEvent) => { if (event.key === CONSENT_KEY || event.key === null) siteAnalytics.reconcile(); };
    window.addEventListener("storage", storage);
    window.addEventListener("pageshow", refresh);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("storage", storage);
      window.removeEventListener("pageshow", refresh);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
      siteAnalytics.dispose();
    };
  }, []);
  useEffect(() => { siteAnalytics.trackPage(pathname); }, [pathname]);
  if (!snapshot.configured || snapshot.privacyBlocked || (snapshot.choice !== "unset" && !snapshot.storageError)) return null;
  return (
    <section className={styles.banner} aria-labelledby="site-analytics-title">
      <h2 id="site-analytics-title" className={styles.title}>{copy.title}</h2>
      <p className={styles.description}>{copy.description}</p>
      <div className={styles.actions}>
        <button type="button" className={styles.button} onClick={() => siteAnalytics.setConsent("allowed")}>{copy.allow}</button>
        <button type="button" className={styles.button} onClick={() => siteAnalytics.setConsent("rejected")}>{copy.reject}</button>
        <Link className={styles.link} href="/privacy">{copy.privacy}</Link>
      </div>
      {snapshot.storageError && <p className={`${styles.note} ${styles.error}`} role="status">{copy.storageError}</p>}
    </section>
  );
}
