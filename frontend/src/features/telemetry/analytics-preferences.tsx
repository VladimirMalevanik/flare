"use client";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";
import { useI18n } from "@/i18n/provider";
import { siteAnalytics } from "@/lib/telemetry/client";
import { telemetryCopy } from "./copy";
import styles from "./telemetry.module.css";

export function AnalyticsPreferences({ compact = true }: { compact?: boolean }) {
  const { locale } = useI18n();
  const copy = telemetryCopy[locale];
  const snapshot = useSyncExternalStore(siteAnalytics.subscribe, siteAnalytics.getSnapshot, siteAnalytics.getServerSnapshot);
  const [open, setOpen] = useState(false);
  useEffect(() => { siteAnalytics.initialize(); }, []);
  if (!snapshot.configured) return null;
  const status = snapshot.storageError ? copy.storageError : snapshot.privacyBlocked ? copy.blocked
    : snapshot.choice === "allowed" ? copy.allowed : snapshot.choice === "rejected" ? copy.rejected : copy.unset;
  const choose = (choice: "allowed" | "rejected") => { siteAnalytics.setConsent(choice); setOpen(false); };
  return (
    <div className={styles.preferences}>
      {!compact && <h3 className={styles.title}>{copy.title}</h3>}
      <p className={`${styles.note} ${snapshot.storageError ? styles.error : ""}`} role="status">{status}</p>
      <button type="button" className={styles.change} aria-expanded={open} onClick={() => setOpen(value => !value)}>{copy.change}</button>
      {open && <div className={styles.choice}>
        <p className={styles.description}>{copy.description}</p>
        <p className={styles.note}>{copy.retention}</p>
        <div className={styles.actions}>
          <Link className={styles.link} href="/analytics">{copy.privacy}</Link>
          <button type="button" className={styles.button} disabled={snapshot.privacyBlocked} onClick={() => choose("allowed")}>{copy.allow}</button>
          <button type="button" className={styles.button} onClick={() => choose("rejected")}>{copy.reject}</button>
          <button type="button" className={styles.link} onClick={() => setOpen(false)}>{copy.cancel}</button>
        </div>
      </div>}
    </div>
  );
}
