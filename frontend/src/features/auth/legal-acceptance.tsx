"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Icon } from "@/components/icons";
import { authRequest } from "@/lib/auth/session";
import { DEFAULT_SUPPORT_EMAIL, supportMailto } from "@/lib/support";

export function LegalAcceptance() {
  const [accepted, setAccepted] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accepted || pending) return;
    setPending(true);
    setError("");
    try {
      await authRequest("accept-legal", {
        termsAccepted: true,
        privacyAccepted: true,
      });
      window.location.replace("/vault");
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Your acceptance could not be saved. Please retry.",
      );
      setPending(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="legal-title">
        <div className="brand">
          <span className="brand-mark"><Icon name="sources" /></span>
          <strong>Flare</strong>
        </div>
        <header className="page-heading">
          <h1 id="legal-title">Review the current documents</h1>
          <p>
            Before continuing, review the current Terms of Service and Privacy Policy.
          </p>
        </header>
        <div className="auth-form">
          <Link className="button secondary" href="/terms" target="_blank">
            Open Terms of Service
          </Link>
          <Link className="button secondary" href="/privacy" target="_blank">
            Open Privacy Policy
          </Link>
          <form onSubmit={submit} className="auth-form" aria-busy={pending}>
            <label className="legal-consent">
              <input
                type="checkbox"
                checked={accepted}
                onChange={(event) => setAccepted(event.target.checked)}
                disabled={pending}
              />
              <span>I have read and agree to the documents listed above.</span>
            </label>
            {error && <p className="auth-error" role="alert">{error}</p>}
            <button className="button primary" disabled={!accepted || pending}>
              {pending ? "Saving…" : "Accept and continue"}
            </button>
          </form>
          <a href={supportMailto("Flare legal documents help")}>Contact support</a>
          <p className="muted auth-support-email">{DEFAULT_SUPPORT_EMAIL}</p>
        </div>
      </section>
    </main>
  );
}
