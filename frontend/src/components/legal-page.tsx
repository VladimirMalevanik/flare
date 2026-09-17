import Link from "next/link";
import type { ReactNode } from "react";

import { BrandMark } from "./brand-mark";

export function LegalPage({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <main className="legal-page">
      <header className="legal-header">
        <Link href="/" className="marketing-brand">
          <BrandMark size={28} />
          Flare
        </Link>
        <Link className="button" href="/register">Get started</Link>
      </header>
      <article className="legal-document">
        <p className="marketing-kicker">Legal</p>
        <h1>{title}</h1>
        <p className="legal-updated">Last updated: {updated}</p>
        {children}
      </article>
      <footer className="legal-footer">
        <Link href="/privacy">Privacy Policy</Link>
        <Link href="/terms">Terms of Service</Link>
        <Link href="/">Back to Flare</Link>
      </footer>
    </main>
  );
}

export function LegalSection({ title, children }: { title: string; children: ReactNode }) {
  return <section><h2>{title}</h2>{children}</section>;
}
