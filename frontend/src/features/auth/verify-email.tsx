"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Icon } from "@/components/icons";
import {
  apiBaseUrl,
  authRequest,
  type Session,
} from "@/lib/auth/session";

type VerificationState = "pending" | "awaiting" | "success" | "invalid";

const neutralResendMessage =
  "If verification is available for that address, a new email will arrive shortly.";

export function VerifyEmail({
  token,
  awaitingEmail,
}: {
  token: string;
  awaitingEmail: boolean;
}) {
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
      setNotice(neutralResendMessage);
    } catch {
      setNotice("Unable to request a new email. Please retry.");
    } finally {
      setResending(false);
    }
  }

  const content = {
    pending: {
      title: "Verifying your email…",
      text: "Please keep this page open for a moment.",
    },
    awaiting: {
      title: "Check your inbox",
      text: "Open the verification link we sent before continuing to Flare.",
    },
    success: {
      title: "Email verified",
      text: "Your existing session can now use the workspace.",
    },
    invalid: {
      title: "Link unavailable",
      text: "This verification link is invalid, expired, or has already been used.",
    },
  }[state];

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="verification-title">
        <div className="brand">
          <span className="brand-mark">
            <Icon name="sources" />
          </span>
          <strong>Flare</strong>
        </div>
        <header className="page-heading">
          <h1 id="verification-title">{content.title}</h1>
          <p>{content.text}</p>
        </header>
        <div className="auth-form" aria-live="polite">
          {notice && <p role="status">{notice}</p>}
          {state === "success" && (
            <Link className="button primary" href="/vault">
              Continue to Flare
            </Link>
          )}
          {(state === "awaiting" || state === "invalid") && email && (
            <button
              className="button secondary"
              type="button"
              onClick={resend}
              disabled={resending}
            >
              {resending ? "Requesting…" : "Resend verification email"}
            </button>
          )}
          {(state === "awaiting" || state === "invalid") && (
            <Link href="/login">Back to sign in</Link>
          )}
        </div>
      </section>
    </main>
  );
}
