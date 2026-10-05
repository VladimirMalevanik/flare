"use client";
import { useI18n } from "@/i18n/provider";
import { LanguageSelector } from "@/components/language-selector";

import Link from "next/link";
import { useState, type KeyboardEvent } from "react";

import { BrandMark } from "@/components/brand-mark";
import { Icon } from "@/components/icons";
import { LandingMotion } from "@/components/landing-motion";

type DemoTab = "capture" | "insights" | "vault";
const demoTabs: DemoTab[] = ["capture", "vault", "insights"];

function Spark({ size = 24 }: { size?: number }) {
  return <span className="landing-spark" style={{ width: size, height: size }}><Icon name="insights" /></span>;
}

export default function Home() {
  const { t, label } = useI18n();

  const [menuOpen, setMenuOpen] = useState(false);
  const [demoTab, setDemoTab] = useState<DemoTab>("insights");
  const [filter, setFilter] = useState("All");
  const [insightOpen, setInsightOpen] = useState(false);

  const [heroEvidence, setHeroEvidence] = useState(false);
  const closeMenu = () => setMenuOpen(false);

  const samples = [
    {
      category: "Risks" as const,
      tag: t("Budget conflict"),
      title: t("You already set this boundary."),
      body: t("Today's launch idea conflicts with the runway limit saved in your June planning note."),
      sources: [
        { title: t("June planning note"), kind: t("Decision"), quote: t("“Keep acquisition spend below $8k/month.”") },
        { title: t("Launch brief"), kind: t("Planning"), quote: t("“Proposed paid launch budget: $14k.”") },
      ],
    },
    {
      category: "Decisions" as const,
      tag: t("Decision to revisit"),
      title: t("Your pricing decision had a condition."),
      body: t("You held the self-serve price at $49 until activation improved. The new pricing proposal is a useful moment to check that condition."),
      sources: [
        { title: t("Pricing note"), kind: t("Decision"), quote: t("“Keep the self-serve plan at $49 until activation improves.”") },
        { title: t("Pricing proposal"), kind: t("Planning"), quote: t("“Move the self-serve plan to $79.”") },
      ],
    },
    {
      category: "Patterns" as const,
      tag: t("Repeated signal"),
      title: t("Two interviews point to the same setup gap."),
      body: t("Both customers found value after setup, but needed help reaching that point. A clearer first step may be worth testing."),
      sources: [
        { title: t("Customer interview — Northstar"), kind: t("Interview"), quote: t("“Once it was set up, it made sense. I needed help getting there.”") },
        { title: t("Customer interview — Acme"), kind: t("Interview"), quote: t("“I wasn't sure what to do first. The walkthrough helped.”") },
      ],
    },
  ];
  const sample = samples.find((entry) => entry.category === filter) ?? samples[0];

  function selectFilter(value: string) {
    setFilter(value);
    setInsightOpen(false);
  }

  function moveTab(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = demoTabs.indexOf(demoTab);
    const next = event.key === "Home" ? demoTabs[0] : event.key === "End" ? demoTabs[2]
      : demoTabs[(index + (event.key === "ArrowRight" ? 1 : 2)) % demoTabs.length];
    setDemoTab(next);
    event.currentTarget.parentElement?.querySelector<HTMLButtonElement>(`#landing-tab-${next}`)?.focus();
  }


  return (
    <main className="landing-page" id="top">
      <header className="landing-nav-shell" onKeyDown={(event) => { if (event.key === "Escape" && menuOpen) { closeMenu(); event.currentTarget.querySelector<HTMLButtonElement>(".landing-menu-button")?.focus(); } }}>
        <div className="landing-container landing-nav">
          <Link className="landing-brand" href="/" aria-label={t("Flare home")}>
            <BrandMark size={28} />
            <span>Flare</span>
          </Link>

          <nav className="landing-nav-links" aria-label={t("Public navigation")}>
            <a href="#problem">{t("Why Flare")}</a>
            <a href="#how-it-works">{t("How it works")}</a>
            <a href="#demo">{t("Demo")}</a>
            <Link href="/login">{t("Sign in")}</Link>
            <Link className="landing-button landing-button-primary landing-button-small" href="/register">
              {t("Get started")}</Link>
          </nav>

          <div className="landing-nav-controls">
            <LanguageSelector />
          <button
            aria-expanded={menuOpen}
            aria-controls="landing-mobile-navigation"
            aria-label={t("Toggle navigation")}
            className="landing-menu-button"
            onClick={() => setMenuOpen((open) => !open)}
            type="button"
          >
            <span />
            <span />
          </button>
          </div>
        </div>

        {menuOpen && (
          <nav className="landing-mobile-nav" id="landing-mobile-navigation" aria-label={t("Mobile navigation")}>
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
              <span>{t("Sample workspace")}</span>
            </div>
            <h2>{t("You already set this boundary.")}</h2>
            <p>
              {t("Today's launch idea conflicts with the runway limit saved in your June planning note.")}</p>
            <button type="button" aria-expanded={heroEvidence} aria-controls="landing-hero-evidence" onClick={() => setHeroEvidence((open) => !open)}>{t("2 supporting sources")}{" "}<span>{heroEvidence ? t("Hide evidence ↑") : t("Open evidence ↓")}</span></button>
            {heroEvidence && <div className="landing-evidence" id="landing-hero-evidence"><div><b>{t("June planning note")}</b><span>{t("“Keep acquisition spend below $8k/month.”")}</span></div><div><b>{t("Launch brief")}</b><span>{t("“Proposed paid launch budget: $14k.”")}</span></div></div>}
          </div>
        </div>
      </section>

      <section className="landing-section landing-problem" id="problem">
        <div className="landing-container landing-problem-grid">
          <div>
            <h2 data-motion-reveal>{t("Startup context disappears in plain sight.")}</h2>
            <div className="landing-problem-lines">
              <p>{t("Decisions hide in chat.")}</p>
              <p>{t("Research sits in tabs.")}</p>
              <p>{t("Meeting notes become archives.")}</p>
              <p>{t("Patterns only surface when it's too late.")}</p>
            </div>
            <p className="landing-problem-answer" data-motion-reveal>
              {t("Flare gives scattered knowledge one place to become useful again.")}</p>
          </div>
        </div>
      </section>

      <section className="landing-section" id="how-it-works">
        <div className="landing-container">
          <div className="landing-section-heading" data-motion-reveal>
            <h2>{t("From scattered context to one useful signal.")}</h2>
          </div>

          <div className="landing-steps">
            <article data-motion-reveal>
              <h3>{t("Capture")}</h3>
              <p>{t("Write a note, paste context, or import bounded CSV, TXT, and Markdown files.")}</p>
            </article>
            <article data-motion-reveal data-motion-delay="90">
              <h3>{t("Choose when to Analyze")}</h3>
              <p>{t("Run Analyze when you want to compare saved context and look for useful connections.")}</p>
            </article>
            <article data-motion-reveal data-motion-delay="180">
              <h3>{t("Review the evidence")}</h3>
              <p>{t("Every published Flare links back to the saved context that supports it.")}</p>
            </article>
          </div>
        </div>
      </section>

      <section className="landing-section landing-demo-section" id="demo">
        <div className="landing-container">
          <div className="landing-section-heading landing-section-heading-row" data-motion-reveal>
            <div>
              <h2>{t("See the signal, then see why.")}</h2>
            </div>
            <p>{t("Try the tabs and open the evidence behind the sample insight.")}</p>
          </div>

          <div className="landing-demo" data-motion-reveal>
            <aside className="landing-demo-sidebar">
              <div className="landing-demo-brand"><BrandMark size={22} /> Flare</div>
              <div className="landing-demo-tabs" role="tablist" aria-label={t("Product preview")}>
                {demoTabs.map((tab) => <button key={tab} id={`landing-tab-${tab}`} role="tab" aria-selected={demoTab === tab}
                  aria-controls="landing-sample-panel" tabIndex={demoTab === tab ? 0 : -1} onKeyDown={moveTab}
                  className={demoTab === tab ? "active" : ""} type="button" onClick={() => setDemoTab(tab)}>
                  <Icon name={tab === "capture" ? "plus" : tab === "vault" ? "vault" : "insights"} />
                  {t(tab === "capture" ? "capture" : tab === "vault" ? "vault" : "flares")}
                </button>)}
              </div>
              <div className="landing-demo-user"><small>{t("Sample workspace")}</small></div>
            </aside>

            <div className="landing-demo-body" id="landing-sample-panel" role="tabpanel" aria-labelledby={`landing-tab-${demoTab}`} tabIndex={0}>
              {demoTab === "capture" && (
                <div className="landing-capture-panel">
                  <p className="landing-demo-kicker">{t("Capture")}</p>
                  <h3>{t("What should Flare remember?")}</h3>
                  <div className="landing-capture-input">
                    <p>
                      {t("Keep the self-serve plan below $49 until activation improves. Enterprise requests can go through a founder-led pilot.")}</p>
                    <span>{t("Planning note · Today")}</span>
                  </div>
                  <button className="landing-button landing-button-primary" type="button" onClick={() => setDemoTab("vault")}>{t("Save to Vault")}</button>
                </div>
              )}

              {demoTab === "insights" && (
                <div>
                  <div className="landing-demo-header">
                    <div><p className="landing-demo-kicker">{t("flares")}</p><h3>{t("Signals worth your attention")}</h3></div>
                    <span>{t("Sample workspace")}</span>
                  </div>
                  <div className="landing-filters" aria-label={t("Insight filters")}>
                    {["All", "Decisions", "Risks", "Patterns"].map((item) => (
                      <button
                        className={filter === item ? "active" : ""}
                        key={item}
                        onClick={() => selectFilter(item)}
                        aria-pressed={filter === item}
                        type="button"
                      >
                        {label(item)}
                      </button>
                    ))}
                  </div>
                  <article className="landing-demo-insight">
                    <div className="landing-card-topline">
                      <span className="landing-signal"><Spark size={15} /> {" "}{t("Hidden connection")}</span>
                      <span>{label(filter === "All" ? "Risks" : filter)}</span>
                    </div>
                    <h4>{sample.title}</h4>
                    <p>{sample.body}</p>
                    <button className="landing-evidence-button" aria-expanded={insightOpen} aria-controls="landing-evidence" onClick={() => setInsightOpen((open) => !open)} type="button">
                      {t("2 supporting sources")}{" "}<span>{insightOpen ? t("Hide evidence ↑") : t("Open evidence ↓")}</span>
                    </button>
                    {insightOpen && (
                      <div className="landing-evidence" id="landing-evidence">
                        {sample.sources.map((source) => <div key={source.title}><b>{source.title}</b><span>{source.quote}</span></div>)}
                      </div>
                    )}
                  </article>

                </div>
              )}

              {demoTab === "vault" && (
                <div>
                  <div className="landing-demo-header">
                    <div><p className="landing-demo-kicker">{t("vault")}</p><h3>{t("Your startup's working memory")}</h3></div>
                    <span>{t("Sample workspace")}</span>
                  </div>

                  <div className="landing-vault-list">
                    <VaultItem meta={t("Decision · Today")} title={t("Pricing boundary for self-serve")} />
                    <VaultItem meta={t("Interview · Tuesday")} title={t("Onboarding call — Northstar Labs")} />
                    <VaultItem meta={t("Research · 12 Jun")} title={t("Competitor workflow teardown")} />
                  </div>
                  <p className="landing-analysis-note">{t("Saving context does not start an analysis. You choose when to run it.")}</p>
                  <button className="landing-button landing-button-primary" type="button" onClick={() => { selectFilter("Decisions"); setDemoTab("insights"); }}>{t("Analyze sample")}</button>
                </div>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="landing-section landing-depth">
        <div className="landing-container landing-depth-grid">
          <div data-motion-reveal>
            <h2>{t("Your startup's memory gets stronger over time.")}</h2>
            <p>
              {t("Notes stay editable and source records stay available. As the Vault grows, Flare has more context to compare before it presents a signal.")}</p>
            <p className="landing-import-note">{t("ZIP imports are one-time copies. Later changes in Notion or Obsidian are not synced automatically.")}</p>
          </div>
          <figure className="landing-vault-figure">
            <div className="landing-vault-orbits" data-motion-loop aria-hidden="true">
              <div className="landing-vault-halo" />
              <div className="landing-vault-ring landing-vault-ring-one" />
              <div className="landing-vault-ring landing-vault-ring-two" />
              <div className="landing-vault-ring landing-vault-ring-three" />
              <div className="landing-vault-turn landing-vault-turn-one landing-loop">
                <div className="landing-vault-satellite"><div className="landing-vault-counter landing-loop">
                  <i className="landing-vault-sphere" /><span>{t("Decision")}</span>
                </div></div>
              </div>
              <div className="landing-vault-turn landing-vault-turn-two landing-loop">
                <div className="landing-vault-satellite"><div className="landing-vault-counter landing-loop">
                  <i className="landing-vault-sphere" /><span>{t("Interview")}</span>
                </div></div>
              </div>
              <div className="landing-vault-turn landing-vault-turn-three landing-loop">
                <div className="landing-vault-satellite"><div className="landing-vault-counter landing-loop">
                  <i className="landing-vault-sphere" /><span>{t("Research")}</span>
                </div></div>
              </div>
              <div className="landing-vault-center"><BrandMark size={40} /><strong>Vault</strong><small>{t("Your saved context")}</small></div>
            </div>
            <figcaption><span>{t("Decisions, interviews, and research in one Vault.")}</span><LandingMotion /></figcaption>
          </figure>
        </div>
      </section>

      <section className="landing-section landing-outcome" data-motion-loop>
        <svg className="landing-ribbon" viewBox="0 0 1440 520" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <defs><linearGradient id="landing-ribbon-blue" x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#003e84" /><stop offset=".42" stopColor="#0071e3" /><stop offset=".7" stopColor="#89ccff" /><stop offset="1" stopColor="#0071e3" />
          </linearGradient></defs>
          <g className="landing-ribbon-drift landing-loop" fill="none" stroke="url(#landing-ribbon-blue)">
            <path strokeWidth="30" d="M-160 410C110 20 350 610 630 230S1110 50 1590 260" />
            <path strokeWidth="2" d="M-160 385C110-5 350 585 630 205S1110 25 1590 235" />
            <path strokeWidth="1" d="M-160 430C110 40 350 630 630 250S1110 70 1590 280" />
          </g>
        </svg>
        <div className="landing-container" data-motion-reveal>
          <blockquote>{t("Less time reconstructing what happened.")}{" "}<span>{t("More time deciding what happens next.")}</span></blockquote>
        </div>
      </section>

      <section className="landing-section landing-difference">
        <div className="landing-container">
          <div className="landing-section-heading" data-motion-reveal><h2>{t("A workspace that shows its reasoning.")}</h2></div>
          <div className="landing-difference-grid" data-motion-reveal>
            <article><span>{t("Typical notes")}</span><p>{t("Store information")}</p><p>{t("Rely on folders")}</p><p>{t("Wait for you to remember")}</p></article>
            <article className="landing-difference-flare"><span><BrandMark size={18} /> Flare</span><p>{t("Connects information")}</p>
              <p><span className="landing-annotation">{t("Links every signal to evidence")}
                <svg viewBox="0 0 400 12" preserveAspectRatio="none" aria-hidden="true"><path d="M2 8Q190 0 398 6" pathLength="1" data-motion-annotation /></svg>
              </span></p><p>{t("Brings forgotten context back")}</p></article>
          </div>
        </div>
      </section>

      <section className="landing-section landing-trust">
        <div className="landing-container" data-motion-reveal>
          <h2>{t("Your workspace stays separated and every insight needs evidence.")}</h2>
          <div className="landing-trust-pills">
            <span>{t("A separate workspace for your team")}</span>
            <span>{t("Editable notes and sources")}</span>
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
