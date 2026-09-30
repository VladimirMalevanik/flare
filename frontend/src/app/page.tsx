"use client";
import { useI18n } from "@/i18n/provider";
import { LanguageSelector } from "@/components/language-selector";

import Link from "next/link";
import { useState } from "react";

import { BrandMark } from "@/components/brand-mark";

type DemoTab = "capture" | "insights" | "vault";

function Spark({ size = 24 }: { size?: number }) {
  return (
    <svg
      aria-hidden="true"
      className="landing-spark"
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      <path d="M12 1.8c.62 5.83 4.37 9.58 10.2 10.2-5.83.62-9.58 4.37-10.2 10.2C11.38 16.37 7.63 12.62 1.8 12 7.63 11.38 11.38 7.63 12 1.8Z" />
    </svg>
  );
}

export default function Home() {
  const { t, label } = useI18n();

  const [menuOpen, setMenuOpen] = useState(false);
  const [demoTab, setDemoTab] = useState<DemoTab>("insights");
  const [filter, setFilter] = useState("All");
  const [insightOpen, setInsightOpen] = useState(false);

  const closeMenu = () => setMenuOpen(false);

  return (
    <main className="landing-page" id="top">
      <header className="landing-nav-shell">
        <div className="landing-container landing-nav">
          <Link className="landing-brand" href="/" aria-label={t("Flare home")}>
            <BrandMark size={28} />
            <span>Flare</span>
          </Link>

          <nav className="landing-nav-links" aria-label={t("Public navigation")}>
            <LanguageSelector />
            <a href="#problem">{t("Why Flare")}</a>
            <a href="#how-it-works">{t("How it works")}</a>
            <a href="#demo">{t("Demo")}</a>
            <Link href="/login">{t("Sign in")}</Link>
            <Link className="landing-button landing-button-primary landing-button-small" href="/register">
              {t("Get started")}</Link>
          </nav>

          <button
            aria-expanded={menuOpen}
            aria-label={t("Toggle navigation")}
            className="landing-menu-button"
            onClick={() => setMenuOpen((open) => !open)}
            type="button"
          >
            <span />
            <span />
          </button>
        </div>

        {menuOpen && (
          <nav className="landing-mobile-nav" aria-label={t("Mobile navigation")}>
            <LanguageSelector />
            <a href="#problem" onClick={closeMenu}>{t("Why Flare")}</a>
            <a href="#how-it-works" onClick={closeMenu}>{t("How it works")}</a>
            <a href="#demo" onClick={closeMenu}>{t("Demo")}</a>
            <Link href="/login" onClick={closeMenu}>{t("Sign in")}</Link>
            <Link className="landing-button landing-button-primary" href="/register" onClick={closeMenu}>
              {t("Get started")}</Link>
          </nav>
        )}
      </header>

      <section className="landing-hero">
        <div className="landing-container landing-hero-inner">
          <p className="landing-eyebrow">{t("Built for founders who forget things")}</p>
          <h1>
            {t("Your notes go quiet.")}{" "}<span>{t("Flare doesn't.")}</span>
          </h1>
          <p className="landing-hero-copy">
            {t("Capture decisions, research, calls, and loose thoughts. Flare keeps the context together and surfaces grounded insights when you choose to analyze it.")}</p>
          <div className="landing-actions">
            <Link className="landing-button landing-button-primary" href="/register">
              {t("Create a workspace")}{" "}<span aria-hidden="true">→</span>
            </Link>
          </div>
          <p className="landing-caption">{t("Early access · Bring your own startup context")}</p>

          <div className="landing-hero-card" aria-label={t("Example Flare insight")}>
            <div className="landing-card-topline">
              <span className="landing-signal"><Spark size={17} /> {" "}{t("Hidden connection")}</span>
              <span>{t("Just now")}</span>
            </div>
            <h2>{t("You already set this boundary.")}</h2>
            <p>
              {t("Today's launch idea conflicts with the runway limit saved in your June planning note.")}</p>
            <button type="button">{t("2 supporting sources")}{" "}<span>{t("Open evidence →")}</span></button>
          </div>
        </div>
      </section>

      <section className="landing-section landing-problem" id="problem">
        <div className="landing-container landing-problem-grid">
          <p className="landing-section-number">{t("01 / THE PROBLEM")}</p>
          <div>
            <h2>{t("Startup context disappears in plain sight.")}</h2>
            <div className="landing-problem-lines">
              <p>{t("Decisions hide in chat.")}</p>
              <p>{t("Research sits in tabs.")}</p>
              <p>{t("Meeting notes become archives.")}</p>
              <p>{t("Patterns only surface when it's too late.")}</p>
            </div>
            <p className="landing-problem-answer">
              {t("Flare gives scattered knowledge one place to become useful again.")}</p>
          </div>
        </div>
      </section>

      <section className="landing-section" id="how-it-works">
        <div className="landing-container">
          <div className="landing-section-heading">
            <p className="landing-section-number">{t("02 / HOW IT WORKS")}</p>
            <h2>{t("From scattered context to one useful signal.")}</h2>
          </div>

          <div className="landing-steps">
            <article>
              <span>01</span>
              <div className="landing-step-icon">＋</div>
              <h3>{t("Capture")}</h3>
              <p>{t("Write a note, paste context, or import bounded CSV, TXT, and Markdown files.")}</p>
            </article>
            <article>
              <span>02</span>
              <div className="landing-step-icon"><Spark size={27} /></div>
              <h3>{t("Flare connects it")}</h3>
              <p>{t("Your saved context is organized so repeated themes and conflicts can surface.")}</p>
            </article>
            <article>
              <span>03</span>
              <div className="landing-step-icon">↗</div>
              <h3>{t("Review the evidence")}</h3>
              <p>{t("Every published Flare links back to the saved context that supports it.")}</p>
            </article>
          </div>
        </div>
      </section>

      <section className="landing-section landing-demo-section" id="demo">
        <div className="landing-container">
          <div className="landing-section-heading landing-section-heading-row">
            <div>
              <p className="landing-section-number">{t("03 / PRODUCT PREVIEW")}</p>
              <h2>{t("See the signal, then see why.")}</h2>
            </div>
            <p>{t("Try the tabs and open the evidence behind the sample insight.")}</p>
          </div>

          <div className="landing-demo">
            <aside className="landing-demo-sidebar">
              <div className="landing-demo-brand"><BrandMark size={22} /> Flare</div>
              <div className="landing-demo-tabs" role="tablist" aria-label={t("Product preview")}>
                <button
                  aria-selected={demoTab === "capture"}
                  className={demoTab === "capture" ? "active" : ""}
                  onClick={() => setDemoTab("capture")}
                  role="tab"
                  type="button"
                >
                  <span>＋</span> {" "}{t("Capture")}</button>
                <button
                  aria-selected={demoTab === "insights"}
                  className={demoTab === "insights" ? "active" : ""}
                  onClick={() => setDemoTab("insights")}
                  role="tab"
                  type="button"
                >
                  <span><Spark size={15} /></span> Flares <b>3</b>
                </button>
                <button
                  aria-selected={demoTab === "vault"}
                  className={demoTab === "vault" ? "active" : ""}
                  onClick={() => setDemoTab("vault")}
                  role="tab"
                  type="button"
                >
                  <span>□</span> Vault
                </button>
              </div>
              <div className="landing-demo-user">
                <span>VM</span>
                <div><strong>Velocity Labs</strong><small>{t("Founder workspace")}</small></div>
              </div>
            </aside>

            <div className="landing-demo-body">
              {demoTab === "capture" && (
                <div className="landing-capture-panel" role="tabpanel">
                  <p className="landing-demo-kicker">{t("QUICK CAPTURE")}</p>
                  <h3>{t("What should Flare remember?")}</h3>
                  <div className="landing-capture-input">
                    <p>
                      {t("Keep the self-serve plan below $49 until activation improves. Enterprise requests can go through a founder-led pilot.")}</p>
                    <span>{t("Planning note · Today")}</span>
                  </div>
                  <button className="landing-button landing-button-primary" type="button">{t("Save to Vault")}</button>
                </div>
              )}

              {demoTab === "insights" && (
                <div role="tabpanel">
                  <div className="landing-demo-header">
                    <div><p className="landing-demo-kicker">FLARES</p><h3>{t("Signals worth your attention")}</h3></div>
                    <span>{t("Updated 4 min ago")}</span>
                  </div>
                  <div className="landing-filters" aria-label={t("Insight filters")}>
                    {["All", "Decisions", "Risks", "Patterns"].map((item) => (
                      <button
                        className={filter === item ? "active" : ""}
                        key={item}
                        onClick={() => setFilter(item)}
                        type="button"
                      >
                        {label(item)}
                      </button>
                    ))}
                  </div>
                  <article className="landing-demo-insight">
                    <div className="landing-card-topline">
                      <span className="landing-signal"><Spark size={15} /> {" "}{t("Hidden connection")}</span>
                      <span>{t("High confidence")}</span>
                    </div>
                    <h4>{t("You already set this boundary.")}</h4>
                    <p>
                      {t("Today's launch idea conflicts with the runway limit saved in your June planning note.")}</p>
                    <button onClick={() => setInsightOpen((open) => !open)} type="button">
                      {t("2 supporting sources")}{" "}<span>{insightOpen ? t("Hide evidence ↑") : t("Open evidence ↓")}</span>
                    </button>
                    {insightOpen && (
                      <div className="landing-evidence">
                        <div><b>{t("June planning note")}</b><span>{t("“Keep acquisition spend below $8k/month.”")}</span></div>
                        <div><b>{t("Launch brief")}</b><span>{t("“Proposed paid launch budget: $14k.”")}</span></div>
                      </div>
                    )}
                  </article>
                  <article className="landing-demo-insight landing-demo-insight-muted">
                    <div className="landing-card-topline"><span>{t("Repeated signal")}</span><span>{t("Yesterday")}</span></div>
                    <h4>{t("Three interviews point to the same onboarding gap.")}</h4>
                    <p>{t("Users understand the value after setup, but they need a faster first win.")}</p>
                  </article>
                </div>
              )}

              {demoTab === "vault" && (
                <div role="tabpanel">
                  <div className="landing-demo-header">
                    <div><p className="landing-demo-kicker">VAULT</p><h3>{t("Your startup's working memory")}</h3></div>
                    <span>{t("148 records")}</span>
                  </div>
                  <div className="landing-vault-search">{t("⌕ Search your workspace")}</div>
                  <div className="landing-vault-list">
                    <VaultItem meta={t("Decision · Today")} title={t("Pricing boundary for self-serve")} />
                    <VaultItem meta={t("Interview · Tuesday")} title={t("Onboarding call — Northstar Labs")} />
                    <VaultItem meta={t("Research · 12 Jun")} title={t("Competitor workflow teardown")} />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="landing-section landing-depth">
        <div className="landing-container landing-depth-grid">
          <div>
            <p className="landing-section-number">{t("04 / THE VAULT")}</p>
            <h2>{t("Your startup's memory gets stronger over time.")}</h2>
            <p>
              {t("Notes stay editable and source records stay available. As the Vault grows, Flare has more context to compare before it presents a signal.")}</p>
            <Link href="/register">{t("Start building your Vault")}{" "}<span>→</span></Link>
          </div>
          <div className="landing-depth-visual" aria-hidden="true">
            <div className="landing-orbit landing-orbit-one" />
            <div className="landing-orbit landing-orbit-two" />
            <div className="landing-orbit landing-orbit-three" />
            <div className="landing-depth-core"><Spark size={38} /><span>148</span><small>{t("connected records")}</small></div>
            <span className="landing-node landing-node-one">{t("Decision")}</span>
            <span className="landing-node landing-node-two">{t("Interview")}</span>
            <span className="landing-node landing-node-three">{t("Research")}</span>
          </div>
        </div>
      </section>

      <section className="landing-section landing-outcome">
        <div className="landing-container">
          <p className="landing-section-number">{t("05 / THE OUTCOME")}</p>
          <blockquote>
            {t("Less time reconstructing what happened.")}{" "}<span>{t("More time deciding what happens next.")}</span>
          </blockquote>
        </div>
      </section>

      <section className="landing-section landing-difference">
        <div className="landing-container">
          <div className="landing-section-heading">
            <p className="landing-section-number">{t("06 / WHY FLARE")}</p>
            <h2>{t("A workspace that shows its reasoning.")}</h2>
          </div>
          <div className="landing-difference-grid">
            <article><span>{t("Typical notes")}</span><p>{t("Store information")}</p><p>{t("Rely on folders")}</p><p>{t("Wait for you to remember")}</p></article>
            <article className="landing-difference-flare"><span><BrandMark size={18} /> Flare</span><p>{t("Connects information")}</p><p>{t("Links every signal to evidence")}</p><p>{t("Brings forgotten context back")}</p></article>
          </div>
        </div>
      </section>

      <section className="landing-section landing-trust">
        <div className="landing-container">
          <p className="landing-section-number">{t("BUILT FOR SENSITIVE CONTEXT")}</p>
          <h2>{t("Your workspace stays separated and every insight needs evidence.")}</h2>
          <div className="landing-trust-pills">
            <span>{t("Secure, HttpOnly sessions")}</span>
            <span>{t("Workspace isolation in PostgreSQL")}</span>
            <span>{t("Evidence-linked Flares")}</span>
            <span>{t("Exportable workspace data")}</span>
          </div>
        </div>
      </section>

      <section className="landing-final-cta">
        <div className="landing-container">
          <Spark size={31} />
          <h2>{t("Give your startup a memory.")}</h2>
          <p>{t("Start capturing the context you'll wish you had later.")}</p>
          <div className="landing-final-actions">
            <Link className="landing-button landing-button-light" href="/register">
              {t("Create a workspace")}{" "}<span>→</span>
            </Link>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <div className="landing-container">
          <Link className="landing-brand" href="#top" aria-label={t("Back to top")}><BrandMark size={28} /> Flare</Link>
          <span>© 2026 Flare</span>
          <nav aria-label={t("Legal and account links")}>
            <Link href="/privacy">{t("Privacy")}</Link>
            <Link href="/terms">{t("Terms")}</Link>
            <Link href="/login">{t("Sign in")}</Link>
          </nav>
        </div>
      </footer>
    </main>
  );
}

function VaultItem({ meta, title }: { meta: string; title: string }) {
  return (
    <article>
      <div><span>{meta}</span><h4>{title}</h4></div>
      <span aria-hidden="true">→</span>
    </article>
  );
}
