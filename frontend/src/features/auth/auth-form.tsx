"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Icon } from "@/components/icons";
import {
  AuthRequestError,
  authRequest,
} from "@/lib/auth/session";

const neutralResendMessage =
  "If verification is available for that address, a new email will arrive shortly.";

export function AuthForm({ register = false }: { register?: boolean }) {
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
            ? caught.message
            : "Check your inbox and verify your email before signing in.",
        );
      } else {
        setError(
          caught instanceof Error
            ? caught.message
            : "Unable to sign in. Please retry.",
        );
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
      setNotice(neutralResendMessage);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Unable to request a new email. Please retry.",
      );
    } finally {
      setResending(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="sources" />
          </span>
          <strong>Flare</strong>
        </div>
        <header className="page-heading">
          <h1 id="auth-title">
            {register ? "Create your workspace" : "Welcome back"}
          </h1>
          <p>
            {register
              ? "One place for your startup context."
              : "Sign in to your Flare workspace."}
          </p>
        </header>
        <form onSubmit={submit} className="auth-form" aria-busy={pending}>
          {register && (
            <label>
              Full name
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
            Email
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
            Password
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
              Use at least 8 characters.
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
                I agree to the <Link href="/terms">Terms of Service</Link> and
                acknowledge the <Link href="/privacy">Privacy Policy</Link>.
              </span>
            </label>
          )}
          {notice && <p role="status">{notice}</p>}
          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}
          <button className="button primary" disabled={pending}>
            {pending
              ? "Please wait…"
              : register
                ? "Create account"
                : "Sign in"}
          </button>
          {verificationEmail && (
            <button
              className="button secondary"
              type="button"
              onClick={resend}
              disabled={resending}
            >
              {resending ? "Requesting…" : "Resend verification email"}
            </button>
          )}
        </form>
        <p className="auth-alternative">
          {register ? "Already have an account? " : "New to Flare? "}
          <Link href={register ? "/login" : "/register"}>
            {register ? "Sign in" : "Create account"}
          </Link>
        </p>
        <nav className="auth-legal-links" aria-label="Legal">
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
        </nav>
      </section>
    </main>
  );
}
