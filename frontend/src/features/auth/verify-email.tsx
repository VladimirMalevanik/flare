"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { LanguageSelector } from "@/components/language-selector";
import { useI18n } from "@/i18n/provider";
import {
  apiBaseUrl,
  authRequest,
  type Session,
} from "@/lib/auth/session";
import { DEFAULT_SUPPORT_EMAIL, supportMailto } from "@/lib/support";

type VerificationState = "pending" | "awaiting" | "success" | "invalid";

export function VerifyEmail({
  token,
  awaitingEmail,
}: {
  token: string;
  awaitingEmail: boolean;
}) {
  const { t, message } = useI18n();
  const [state, setState] = useState<VerificationState>(
    token ? "pending" : "awaiting",
  );
  const [email, setEmail] = useState("");
  const [resending, setResending] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    if (token) {
      void authRequest("verify-email", { token })
        .then(() => {
          if (active) setState("success");
        })
        .catch(() => {
          if (active) setState("invalid");
        });
      if (typeof window !== "undefined") {
        window.history.replaceState(null, "", "/verify-email");
      }
    }
    if (awaitingEmail || token) {
      void fetch(`${apiBaseUrl}/auth/me`, {
        credentials: "include",
        cache: "no-store",
      })
        .then(async (response) =>
          response.ok ? ((await response.json()) as Session) : null,
        )
        .then((session) => {
          if (active && session) setEmail(session.user.email);
        })
        .catch(() => undefined);
    }
    return () => {
      active = false;
    };
  }, [awaitingEmail, token]);

  async function resend() {
    if (!email || resending) return;
    setResending(true);
    setNotice("");
    try {
      await authRequest("resend-verification", { email });
      setNotice("neutralResend");
    } catch {
      setNotice("resendFallback");
    } finally {
      setResending(false);
    }
  }

  const content = {
    pending: {
      title: t("verifyingEmail"),
      text: t("verifyingEmailDetail"),
    },
    awaiting: {
      title: t("checkInbox"),
      text: t("checkInboxDetail"),
    },
    success: {
      title: t("emailVerified"),
      text: t("emailVerifiedDetail"),
    },
    invalid: {
      title: t("linkUnavailable"),
      text: t("linkUnavailableDetail"),
    },
  }[state];

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="verification-title">
        <div className="auth-language"><LanguageSelector /></div>
        <div className="brand">
          <span className="brand-mark">
            <BrandMark size={32} />
          </span>
          <strong>Flare</strong>
        </div>
        <header className="page-heading">
          <h1 id="verification-title">{content.title}</h1>
          <p>{content.text}</p>
        </header>
        <div className="auth-form" aria-live="polite">
          {notice && <p role="status">{message(notice)}</p>}
          {state === "success" && (
            <Link className="button primary" href="/vault">
              {t("continueToFlare")}
            </Link>
          )}
          {(state === "awaiting" || state === "invalid") && email && (
            <button
              className="button secondary"
              type="button"
              onClick={resend}
              disabled={resending}
            >
              {resending ? t("requesting") : t("resendVerification")}
            </button>
          )}
          {(state === "awaiting" || state === "invalid") && (
            <Link href="/login">{t("backToSignIn")}</Link>
          )}
          <a href={supportMailto("Flare email verification help")}>{t("contactSupport")}</a>
          <p className="muted auth-support-email">{DEFAULT_SUPPORT_EMAIL}</p>
        </div>
      </section>
    </main>
  );
}
