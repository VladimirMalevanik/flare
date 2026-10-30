"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { BrandMark } from "@/components/brand-mark";
import { LanguageSelector } from "@/components/language-selector";
import { useI18n } from "@/i18n/provider";
import type { TranslationKey } from "@/i18n/en";
import { AuthRequestError, authRequest } from "@/lib/auth/session";
import { supportMailto } from "@/lib/support";
import { consumeResetToken } from "./reset-token";

type Phase = "loading" | "ready" | "sent" | "success" | "invalid" | "unconfirmed";

export function PasswordRecovery({ reset = false }: { reset?: boolean }) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>(reset ? "loading" : "ready");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<TranslationKey | "">("");
  const token = useRef<string | null>(null);
  const submitting = useRef(false);
  const mounted = useRef(true);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    mounted.current = true;
    let active = true;
    // A different email link can change only the fragment of this same page.
    // Reload the new document so it cannot reuse the old token/form/request.
    const reload = () => window.location.reload();
    if (reset) {
      window.addEventListener("hashchange", reload);
      // React's development setup/cleanup cycle must not consume the link twice.
      if (token.current === null) token.current = consumeResetToken(window.location, window.history);
      void Promise.resolve().then(() => {
        if (active) setPhase(current => current === "loading" ? (token.current ? "ready" : "invalid") : current);
      });
    }
    return () => { active = false; mounted.current = false; window.removeEventListener("hashchange", reload); };
  }, [reset]);

  useEffect(() => {
    if (["sent", "success", "invalid", "unconfirmed"].includes(phase)) heading.current?.focus();
  }, [phase]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || !mounted.current || phase !== "ready") return;
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") ?? "");
    const email = String(data.get("email") ?? "").trim().toLowerCase();
    const address = email.split("@");
    if (!reset && (!address[0] || address.length !== 2 || !address[1].includes(".") || /\s/.test(email) || email.length > 254)) {
      setError("Enter a valid email address.");
      return;
    }
    if (reset && password !== String(data.get("confirmPassword") ?? "")) {
      setError("Passwords do not match.");
      return;
    }
    if (reset && (Array.from(password).length < 8 || Array.from(password).length > 128)) {
      setError("Use a password with 8 to 128 characters.");
      return;
    }
    submitting.current = true;
    setPending(true);
    setError("");
    try {
      await authRequest(reset ? "reset-password" : "forgot-password", reset
        ? { token: token.current, password }
        : { email });
      if (mounted.current) {
        token.current = "";
        setPhase(reset ? "success" : "sent");
      }
    } catch (caught) {
      if (!mounted.current) return;
      const code = caught instanceof AuthRequestError ? caught.code : "request_outcome_unknown";
      if (code === "password_reset_invalid") {
        token.current = "";
        setPhase("invalid");
      } else if (code === "request_outcome_unknown" || (reset && caught instanceof AuthRequestError && caught.status >= 500)) {
        token.current = "";
        setPhase("unconfirmed");
      } else {
        setError(code === "password_recovery_busy"
          ? "Please wait a moment and try again."
          : "Password recovery is temporarily unavailable. Please try again later.");
      }
    } finally {
      submitting.current = false;
      if (mounted.current) setPending(false);
    }
  }

  const title = phase === "success" ? t("Password updated") : phase === "sent" ? t("Check your inbox")
    : phase === "invalid" ? t("Reset link unavailable") : phase === "unconfirmed" ? t("Request not confirmed")
    : reset ? t("Choose a new password") : t("Forgot your password?");
  return <main className="auth-page">
    <section className="auth-panel" aria-labelledby="recovery-title">
      <div className="auth-language"><LanguageSelector /></div>
      <div className="brand"><span className="brand-mark"><BrandMark size={32} /></span><strong>Flare</strong></div>
      <header className="page-heading">
        <h1 id="recovery-title" ref={heading} tabIndex={-1}>{title}</h1>
        {["ready", "loading"].includes(phase) && <p>{reset ? t("Reset your password securely. Your saved workspace stays the same.") : t("Enter your account email and we’ll send a password reset link if recovery is available.")}</p>}
      </header>
      {phase === "loading" && <p role="status">{t("Checking reset link…")}</p>}
      {phase === "ready" && <form onSubmit={submit} className="auth-form" aria-busy={pending}>
        {reset ? <>
          <label>{t("New password")}<input name="password" type="password" autoComplete="new-password" required maxLength={128} disabled={pending} aria-describedby="recovery-password-help" /></label>
          <p className="muted" id="recovery-password-help">{t("Use a password with 8 to 128 characters.")}</p>
          <label>{t("Confirm new password")}<input name="confirmPassword" type="password" autoComplete="new-password" required maxLength={128} disabled={pending} /></label>
        </> : <label>{t("email")}<input name="email" type="email" autoComplete="username" required maxLength={254} disabled={pending} /></label>}
        {error && <p className="auth-error" role="alert">{t(error)}</p>}
        <button className="button primary" disabled={pending}>{pending ? t("pleaseWait") : reset ? t("Save new password") : t("Send reset link")}</button>
      </form>}
      <div className={`auth-form${phase === "ready" ? " auth-alternative" : ""}`} aria-live="polite">
        {phase === "sent" && <>
          <p role="status">{t("If recovery is available for that address, an email will arrive shortly. Check spam too. Wait one minute before requesting another link.")}</p>
        </>}
        {phase === "success" && <p role="status">{t("Your password was changed and previous sessions have ended. Sign in with your new password.")}</p>}
        {phase === "invalid" && <p role="alert">{t("This reset link is invalid, expired or already used. Request a new link to continue.")}</p>}
        {phase === "unconfirmed" && <p role="alert">{reset
          ? t("We could not confirm the password change. Try signing in with the new password before requesting another link.")
          : t("We could not confirm your request. Check your inbox before requesting another link.")}</p>}
        {(phase === "success" || (reset && phase === "unconfirmed")) && <Link className="button primary" href="/login">{t("signIn")}</Link>}
        {reset && ["invalid", "unconfirmed"].includes(phase) && <Link className={`button ${phase === "invalid" ? "primary" : "secondary"}`} href="/forgot-password">{t("Request a new reset link")}</Link>}
        {(phase === "sent" || (!reset && phase === "unconfirmed")) && <button className="button secondary" onClick={() => setPhase("ready")}>{t("Try another address")}</button>}
        {phase !== "success" && !(reset && phase === "unconfirmed") && <Link href="/login">{t("backToSignIn")}</Link>}
      </div>
      <nav className="auth-legal-links" aria-label={t("legalAndSupport")}>
        <Link href="/privacy">{t("privacy")}</Link><Link href="/terms">{t("terms")}</Link>
        <a href={supportMailto("Flare account access")}>{t("contactSupport")}</a>
      </nav>
    </section>
  </main>;
}
