"use client";
import Link from "next/link";
import { useState } from "react";
import { useI18n } from "@/i18n/provider";
import { apiBaseUrl } from "@/lib/auth/session";
import { acquisitionChoice, chooseAcquisition, withdrawAcquisition } from "@/lib/auth/acquisition";
import { acquisitionCopy } from "./copy";
import { useAcquisitionPolicy, useAcquisitionPrivacy } from "./use-policy";
import styles from "@/features/telemetry/telemetry.module.css";

export function AcquisitionPreferences({ account = false }: { account?: boolean }) {
  const { locale } = useI18n();
  const copy = acquisitionCopy[locale];
  const policy = useAcquisitionPolicy("preferences");
  const blocked = useAcquisitionPrivacy();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState(false);
  async function reject() {
    setBusy(true); setError(false);
    if (policy) chooseAcquisition(policy, false);
    const success = await withdrawAcquisition(apiBaseUrl, account ? true : "optional");
    setStatus(success ? (account ? copy.removed : copy.rejected) : copy.withdrawalError);
    setError(!success); setBusy(false);
  }
  function allow() {
    if (!policy) return;
    const saved = chooseAcquisition(policy, true);
    setStatus(saved ? copy.allowed : copy.error); setError(!saved);
  }
  // Withdrawal stays available even when policy is disabled or unavailable.
  return <div className={styles.preferences}>
    <h3 className={styles.title}>{copy.title}</h3>
    <p className={styles.description}>{account ? copy.account : copy.description}</p>
    <p className={styles.note}>{copy.retention}</p>
    <p className={`${styles.note} ${error ? styles.error : ""}`} role="status">{status || (blocked ? copy.blocked : policy && acquisitionChoice(policy) === "allowed" ? copy.allowed : copy.unset)}</p>
    <div className={styles.actions}>
      {!account && policy && <button type="button" className={styles.button} disabled={busy || blocked} onClick={allow}>{copy.allow}</button>}
      <button type="button" className={styles.button} disabled={busy} onClick={() => void reject()}>{busy ? copy.busy : account ? copy.withdraw : copy.reject}</button>
      <Link className={styles.link} href="/measurement">{copy.details}</Link>
    </div>
  </div>;
}
