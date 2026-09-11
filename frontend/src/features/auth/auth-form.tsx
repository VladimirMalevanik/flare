"use client";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { authRequest } from "@/lib/auth/session";
import { Icon } from "@/components/icons";

export function AuthForm({ register = false }: { register?: boolean }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const data = new FormData(event.currentTarget);
    setPending(true);
    setError("");
    try {
      await authRequest(register ? "register" : "login", {
        email: data.get("email"), password: data.get("password"),
        ...(register ? { name: data.get("name") } : {}),
      });
      // Full navigation clears any previous user's client state and route cache.
      window.location.replace("/vault");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Unable to sign in. Please retry.");
      setPending(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="brand"><span className="brand-mark"><Icon name="sources" /></span><strong>Flare</strong></div>
        <header className="page-heading">
          <h1 id="auth-title">{register ? "Create your workspace" : "Welcome back"}</h1>
          <p>{register ? "One place for your startup context." : "Sign in to your Flare workspace."}</p>
        </header>
        <form onSubmit={submit} className="auth-form" aria-busy={pending}>
          {register && <label>Full name<input name="name" autoComplete="name" required maxLength={100} disabled={pending} /></label>}
          <label>Email<input name="email" type="email" autoComplete="username" required maxLength={254} disabled={pending} /></label>
          <label>Password<input name="password" type="password" autoComplete={register ? "new-password" : "current-password"} minLength={register ? 8 : 1} maxLength={128} required disabled={pending} aria-describedby={register ? "password-help" : undefined} /></label>
          {register && <p id="password-help" className="muted">Use at least 8 characters.</p>}
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="button primary" disabled={pending}>{pending ? "Please wait…" : register ? "Create account" : "Sign in"}</button>
        </form>
        <p className="auth-alternative">{register ? "Already have an account? " : "New to Flare? "}<Link href={register ? "/login" : "/register"}>{register ? "Sign in" : "Create account"}</Link></p>
      </section>
    </main>
  );
}
