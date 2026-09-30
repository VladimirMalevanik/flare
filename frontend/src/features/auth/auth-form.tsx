"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { BrandMark } from "@/components/brand-mark";
import { LanguageSelector } from "@/components/language-selector";
import { useI18n } from "@/i18n/provider";
import {
  AuthRequestError,
  authRequest,
} from "@/lib/auth/session";
import { DEFAULT_SUPPORT_EMAIL, supportMailto } from "@/lib/support";

export function AuthForm({ register = false }: { register?: boolean }) {
  const { t, message } = useI18n();
  const [pending, setPending] = useState(false);
  const [resending, setResending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [verificationEmail, setVerificationEmail] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const data = new FormData(event.currentTarget);
    const email = String(data.get("email") ?? "").trim().toLowerCase();
    setPending(true);
    setError("");
    setNotice("");
    try {
      const result = await authRequest(register ? "register" : "login", {
        email,
        password: data.get("password"),
        ...(register
          ? {
              name: data.get("name"),
              termsAccepted: data.get("legalAccepted") === "on",
              privacyAccepted: data.get("legalAccepted") === "on",
            }
          : {}),
      });
      if (register && result.emailVerificationRequired) {
        window.location.replace("/verify-email?pending=1");
        return;
      }
      // Full navigation clears any previous user's client state and route cache.
      window.location.replace("/vault");
    } catch (caught) {
      if (
        caught instanceof AuthRequestError &&
        ["email_verification_required", "email_delivery_failed"].includes(
          caught.code ?? "",
        )
      ) {
        setVerificationEmail(email);
        setNotice(
          caught.code === "email_delivery_failed"
            ? "emailDeliveryFailed"
            : "verificationRequired",
        );
      } else {
        setError(caught instanceof AuthRequestError && caught.code === "invalid_credentials"
          ? "errorCredentials"
          : caught instanceof AuthRequestError && caught.code === "registration_unavailable"
            ? "registrationUnavailable"
            : "authFallback");
      }
      setPending(false);
    }
  }

  async function resend() {
    if (!verificationEmail || resending) return;
    setResending(true);
    setError("");
    try {
      await authRequest("resend-verification", { email: verificationEmail });
      setNotice("neutralResend");
    } catch {
      setError("resendFallback");
    } finally {
      setResending(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-language"><LanguageSelector /></div>
        <div className="brand">
          <span className="brand-mark">
            <BrandMark size={32} />
          </span>
          <strong>Flare</strong>
        </div>
        <header className="page-heading">
          <h1 id="auth-title">
            {register ? t("createYourWorkspace") : t("welcomeBack")}
          </h1>
          <p>
            {register
              ? t("registerDescription")
              : t("loginDescription")}
          </p>
        </header>
        <form onSubmit={submit} className="auth-form" aria-busy={pending}>
          {register && (
            <label>
              {t("fullName")}
              <input
                name="name"
                autoComplete="name"
                required
                maxLength={100}
                disabled={pending}
              />
            </label>
          )}
          <label>
            {t("email")}
            <input
              name="email"
              type="email"
              autoComplete="username"
              required
              maxLength={254}
              disabled={pending}
            />
          </label>
          <label>
            {t("password")}
            <input
              name="password"
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              minLength={register ? 8 : 1}
              maxLength={128}
              required
              disabled={pending}
              aria-describedby={register ? "password-help" : undefined}
            />
          </label>
          {register && (
            <p id="password-help" className="muted">
              {t("passwordHelp")}
            </p>
          )}
          {register && (
            <label className="legal-consent">
              <input
                name="legalAccepted"
                type="checkbox"
                required
                disabled={pending}
              />
              <span>
                {t("agreePrefix")} <Link href="/terms">{t("termsOfService")}</Link> {t("agreeMiddle")} <Link href="/privacy">{t("privacyPolicy")}</Link>.
              </span>
            </label>
          )}
          {notice && <p role="status">{message(notice)}</p>}
          {error && (
            <p className="auth-error" role="alert">
              {message(error)}
            </p>
          )}
          <button className="button primary" disabled={pending}>
            {pending
              ? t("pleaseWait")
              : register
                ? t("createAccount")
                : t("signIn")}
          </button>
          {verificationEmail && (
            <button
              className="button secondary"
              type="button"
              onClick={resend}
              disabled={resending}
            >
              {resending ? t("requesting") : t("resendVerification")}
            </button>
          )}
        </form>
        <p className="auth-alternative">
          {register ? t("alreadyHaveAccount") : t("newToFlare")} {" "}
          <Link href={register ? "/login" : "/register"}>
            {register ? t("signIn") : t("createAccount")}
          </Link>
        </p>
        <nav className="auth-legal-links" aria-label={t("legalAndSupport")}>
          <Link href="/privacy">{t("privacy")}</Link>
          <Link href="/terms">{t("terms")}</Link>
          <a href={supportMailto("Flare support request")}>{t("contactSupport")}</a>
        </nav>
        <p className="muted auth-support-email">{DEFAULT_SUPPORT_EMAIL}</p>
      </section>
    </main>
  );
}
