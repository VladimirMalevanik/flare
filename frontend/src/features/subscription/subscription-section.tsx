"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { useSession } from "@/components/auth-session";
import { Icon } from "@/components/icons";
import { useI18n } from "@/i18n/provider";
import { billingStatus, paddleSandboxCheckout } from "@/lib/billing/paddle-sandbox";
import { hasUnexpiredProAccess } from "@/lib/billing/billing-status-controller";
import { subscriptionCopy } from "./subscription-copy";
import styles from "./subscription-section.module.css";

const plans = ["free", "pro", "team"] as const;

export function SubscriptionSection() {
  const { locale } = useI18n();
  const copy = subscriptionCopy[locale];
  const session = useSession();
  const checkout = useSyncExternalStore(
    paddleSandboxCheckout.subscribe,
    paddleSandboxCheckout.getSnapshot,
    paddleSandboxCheckout.getServerSnapshot,
  );
  const billing = useSyncExternalStore(billingStatus.subscribe, billingStatus.getSnapshot, billingStatus.getServerSnapshot);
  const [notice, setNotice] = useState<"team" | "free" | "open" | null>(null);
  const userId = session?.user.id;
  const workspaceId = session?.workspace.id;
  useEffect(() => {
    billingStatus.start(userId && workspaceId ? { userId, workspaceId } : null,
      paddleSandboxCheckout.getSnapshot().completionRevision);
    return () => billingStatus.stop();
  }, [userId, workspaceId]);
  useEffect(() => {
    billingStatus.confirmCheckout(checkout.completionRevision);
  }, [checkout.completionRevision, userId, workspaceId]);
  useEffect(() => () => paddleSandboxCheckout.cancelPendingCheckout(), []);
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") void billingStatus.refresh();
    };
    window.addEventListener("focus", refresh);
    window.addEventListener("pageshow", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("pageshow", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [userId, workspaceId]);
  const busy = checkout.phase === "loading" || checkout.phase === "open" || checkout.phase === "complete";
  const cachedStatus = billing.status?.workspaceId === workspaceId ? billing.status : null;
  const verifiedStatus = cachedStatus?.plan === "pro" && !hasUnexpiredProAccess(cachedStatus) ? null : cachedStatus;
  const currentPlan = verifiedStatus?.plan ?? null;
  const canBuyPro = billing.phase === "ready" && verifiedStatus?.checkoutAvailable
    && verifiedStatus.canManageBilling && currentPlan === "free" && !billing.pendingConfirmation
    && !billing.confirmationTimedOut;

  async function buyPro() {
    if (!canBuyPro || busy) return;
    setNotice(null);
    try {
      await paddleSandboxCheckout.openProCheckout(session?.user ?? null, locale);
    } catch {
      setNotice("open");
    }
  }

  const errorMessage = notice === "team" || notice === "free" ? null : checkout.error
    ? copy.errors[checkout.error]
    : notice === "open" ? copy.errors.open : null;
  const statusMessage = errorMessage
    ?? (notice === "team" ? copy.teamUnavailable
      : notice === "free" ? copy.freeUnavailable
      : checkout.phase === "loading" ? copy.loadingStatus
      : checkout.phase === "open" ? copy.openStatus
      : currentPlan === "pro" ? copy.proConfirmed
      : billing.pendingConfirmation ? copy.confirming
      : billing.confirmationTimedOut ? copy.confirmationDelayed
      : checkout.phase === "complete" ? copy.completeStatus
      : null);
  const billingMessage = billing.error ? copy.billingErrors[billing.error]
    : billing.phase === "loading" && !verifiedStatus ? copy.checking
    : verifiedStatus && !verifiedStatus.canManageBilling ? copy.ownerOnly
    : verifiedStatus && !verifiedStatus.checkoutAvailable && currentPlan !== "pro" ? copy.backendSetup
    : null;

  return (
    <section id="subscription" className="card settings-section" aria-labelledby="subscription-title">
      <header>
        <div className={styles.heading}>
          <h2 id="subscription-title"><Icon name="vault" />{copy.title}</h2>
          <span className={styles.badge}>{copy.sandbox}</span>
        </div>
        <p className="muted meta">{copy.description}</p>
      </header>
      <div className={styles.plans}>
        {plans.map((plan) => {
          const selected = plan === currentPlan;
          const details = copy[plan];
          const buttonText = selected ? copy.current
            : plan === "pro" && checkout.phase === "loading" ? copy.loading
            : plan === "pro" && checkout.phase === "open" ? copy.checkoutOpen
            : copy.buy;
          return (
            <article key={plan} className={`${styles.plan} ${selected ? styles.selected : ""}`}>
              <h3>{details.name}</h3>
              <p className={styles.description}>{details.description}</p>
              {plan === "pro" && <p className={styles.trial}>{copy.pro.trial}</p>}
              <p className={styles.benefitLabel}>{plan === "free" ? copy.included : copy.planned}</p>
              <ul className={styles.benefits}>
                {details.benefits.map((benefit) => (
                  <li key={benefit}><Icon name="check" /><span>{benefit}</span></li>
                ))}
              </ul>
              <button
                type="button"
                className={`button ${selected ? styles.current : "primary"}`}
                disabled={selected || busy || (plan === "pro" && !canBuyPro) || (plan === "free" && !currentPlan)}
                aria-label={(selected ? copy.currentPlan : copy.buyPlan).replace("{plan}", details.name)}
                aria-busy={plan === "pro" && checkout.phase === "loading"}
                onClick={plan === "pro" ? () => void buyPro() : () => setNotice(plan === "free" ? "free" : "team")}
              >
                {buttonText}
              </button>
            </article>
          );
        })}
      </div>
      <p className={styles.note}>{copy.sandboxNote}</p>
      {billingMessage && <p className={`${styles.status} ${billing.error ? styles.error : ""}`} role={billing.error ? "alert" : "status"}>{billingMessage}</p>}
      {statusMessage && (
        <p className={`${styles.status} ${errorMessage ? styles.error : ""}`} role={errorMessage ? "alert" : "status"}>
          {statusMessage}
        </p>
      )}
      {(billing.error || billing.confirmationTimedOut) && (
        <button type="button" className="button" disabled={billing.phase === "loading"} onClick={() => void billingStatus.checkAgain()}>{copy.refresh}</button>
      )}
    </section>
  );
}
