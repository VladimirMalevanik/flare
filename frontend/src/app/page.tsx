import Link from "next/link";

export default function Home() {
  return (
    <main className="marketing-page">
      <header className="marketing-nav">
        <Link href="/" className="marketing-brand" aria-label="Flare home">
          <span className="marketing-spark" aria-hidden="true">✦</span>
          Flare
        </Link>
        <nav aria-label="Public navigation">
          <a href="#how-it-works">How it works</a>
          <a href="#preview">Preview</a>
          <Link href="/login">Sign in</Link>
          <Link className="button primary" href="/register">Get started</Link>
        </nav>
      </header>

      <section className="marketing-hero">
        <p className="marketing-kicker">AI second brain for founders</p>
        <h1>Your notes go quiet. <span>Flare doesn&apos;t.</span></h1>
        <p className="marketing-lead">
          Capture decisions, research, calls, and loose thoughts. Flare keeps the
          context together and surfaces grounded insights when you choose to analyze it.
        </p>
        <div className="marketing-actions">
          <Link className="button primary" href="/register">Create a workspace</Link>
          <a className="button" href="#preview">See how it works</a>
        </div>
        <p className="marketing-note">Early access · Bring your own startup context</p>
      </section>

      <section className="marketing-section" id="how-it-works">
        <p className="marketing-kicker">How it works</p>
        <h2>From scattered context to one useful signal.</h2>
        <div className="marketing-steps">
          <article><span>01</span><h3>Capture</h3><p>Write a note or import bounded CSV, TXT, and Markdown files.</p></article>
          <article><span>02</span><h3>Keep control</h3><p>Edit sources, choose a daily time, or start an analysis yourself.</p></article>
          <article><span>03</span><h3>Review evidence</h3><p>Every published Flare links back to the saved context that supports it.</p></article>
        </div>
      </section>

      <section className="marketing-section marketing-preview" id="preview">
        <div>
          <p className="marketing-kicker">Product preview</p>
          <h2>Useful because it remembers why.</h2>
          <p>
            Flare can connect a new decision with an older note, flag a repeated
            problem, or bring an unresolved question back into view.
          </p>
        </div>
        <article className="marketing-insight-card">
          <span>Hidden connection</span>
          <h3>You already set this boundary.</h3>
          <p>
            Today&apos;s launch idea conflicts with the runway limit saved in your June
            planning note.
          </p>
          <footer>2 supporting sources · Open evidence</footer>
        </article>
      </section>

      <section className="marketing-section marketing-trust">
        <p className="marketing-kicker">Built for sensitive context</p>
        <h2>Your workspace stays separated and every insight needs evidence.</h2>
        <div>
          <p>Secure, HttpOnly sessions</p>
          <p>Workspace isolation in PostgreSQL</p>
          <p>Manual or once-daily analysis</p>
          <p>Exportable workspace data</p>
        </div>
      </section>

      <footer className="marketing-footer">
        <span>© 2026 Flare</span>
        <nav aria-label="Legal and account links">
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/login">Sign in</Link>
        </nav>
      </footer>
    </main>
  );
}
