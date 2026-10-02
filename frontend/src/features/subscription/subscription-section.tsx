"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { useSession } from "@/components/auth-session";
import { Icon } from "@/components/icons";
import { useI18n } from "@/i18n/provider";
import { paddleSandboxCheckout } from "@/lib/billing/paddle-sandbox";
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
  const [notice, setNotice] = useState<"team" | "open" | null>(null);
  useEffect(() => () => paddleSandboxCheckout.cancelPendingCheckout(), []);
  const busy = checkout.phase === "loading" || checkout.phase === "open" || checkout.phase === "complete";

  // Billing access is assigned by the server in a later integration stage.
  // Completing a sandbox checkout must never grant a paid plan in this UI.
  const currentPlan = "free";

  async function buyPro() {
    setNotice(null);
    try {
      await paddleSandboxCheckout.openProCheckout(session?.user ?? null, locale);
    } catch {
      setNotice("open");
    }
  }

  const errorMessage = notice === "team" ? null : checkout.error
    ? copy.errors[checkout.error]
    : notice === "open" ? copy.errors.open : null;
  const statusMessage = errorMessage
    ?? (notice === "team" ? copy.teamUnavailable
      : checkout.phase === "complete" ? copy.completeStatus
      : checkout.phase === "loading" ? copy.loadingStatus
      : checkout.phase === "open" ? copy.openStatus
      : null);

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
              <p className={styles.benefitLabel}>{selected ? copy.included : copy.planned}</p>
              <ul className={styles.benefits}>
                {details.benefits.map((benefit) => (
                  <li key={benefit}><Icon name="check" /><span>{benefit}</span></li>
                ))}
              </ul>
              <button
                type="button"
                className={`button ${selected ? styles.current : "primary"}`}
                disabled={selected || busy}
                aria-label={(selected ? copy.currentPlan : copy.buyPlan).replace("{plan}", details.name)}
                aria-busy={plan === "pro" && checkout.phase === "loading"}
                onClick={plan === "pro" ? () => void buyPro() : () => setNotice("team")}
              >
                {buttonText}
              </button>
            </article>
          );
        })}
      </div>
      <p className={styles.note}>{copy.sandboxNote}</p>
      {statusMessage && (
        <p className={`${styles.status} ${errorMessage ? styles.error : ""}`} role={errorMessage ? "alert" : "status"}>
          {statusMessage}
        </p>
      )}
    </section>
  );
}
