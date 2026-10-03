"use client";

import Link from "next/link";
import { useState, type KeyboardEvent } from "react";
import { BrandMark } from "@/components/brand-mark";
import { LanguageSelector } from "@/components/language-selector";
import { useI18n } from "@/i18n/provider";

type DemoTab = "capture" | "insights" | "vault";
const demoTabs: DemoTab[] = ["capture", "vault", "insights"];

function Spark({ size = 20 }: { size?: number }) {
  return <svg aria-hidden="true" className="landing-spark" height={size} width={size} viewBox="0 0 24 24">
    <path d="M12 1.8c.62 5.83 4.37 9.58 10.2 10.2-5.83.62-9.58 4.37-10.2 10.2C11.38 16.37 7.63 12.62 1.8 12 7.63 11.38 11.38 7.63 12 1.8Z" />
  </svg>;
}

export default function Home() {
  const { t } = useI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const [demoTab, setDemoTab] = useState<DemoTab>("insights");
  const [filter, setFilter] = useState("All");
  const [insightOpen, setInsightOpen] = useState(false);
  const closeMenu = () => setMenuOpen(false);

  const samples = [
    {
      category: "Risks" as const,
      tag: t("Budget conflict"),
      title: t("This launch plan crosses an earlier limit."),
      body: t("The proposed $14k launch budget is above the $8k monthly limit in your planning note. Revisit the plan or the limit before you commit."),
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

  return <main className="landing-page" id="top">
    <header className="landing-nav-shell" onKeyDown={(event) => {
      if (event.key === "Escape" && menuOpen) {
        closeMenu();
        event.currentTarget.querySelector<HTMLButtonElement>(".landing-menu-button")?.focus();
      }
    }}>
      <div className="landing-container landing-nav">
        <Link className="landing-brand" href="/" aria-label={t("Flare home")}><BrandMark size={28} /><span>Flare</span></Link>
        <div className="landing-nav-actions">
          <nav className="landing-nav-links" aria-label={t("Public navigation")}>
            <a href="#how-it-works">{t("How it works")}</a>
            <a href="#sources">{t("Sources")}</a>
            <a href="#demo">{t("Demo")}</a>
          </nav>
          <LanguageSelector compact={false} />
          <Link className="landing-nav-signin" href="/login">{t("Sign in")}</Link>
          <Link className="landing-button landing-button-primary landing-button-small landing-nav-cta" href="/register">{t("Get started")}</Link>
          <button aria-expanded={menuOpen} aria-controls="landing-mobile-navigation" aria-label={t("Toggle navigation")}
            className="landing-menu-button" type="button" onClick={() => setMenuOpen((open) => !open)}><span /><span /></button>
        </div>
      </div>
      {menuOpen && <nav className="landing-mobile-nav" id="landing-mobile-navigation" aria-label={t("Mobile navigation")}>
        <a href="#how-it-works" onClick={closeMenu}>{t("How it works")}</a>
        <a href="#sources" onClick={closeMenu}>{t("Sources")}</a>
        <a href="#demo" onClick={closeMenu}>{t("Demo")}</a>
        <Link href="/login" onClick={closeMenu}>{t("Sign in")}</Link>
        <Link className="landing-button landing-button-primary" href="/register" onClick={closeMenu}>{t("Create a workspace")}</Link>
      </nav>}
    </header>

    <section className="landing-hero">
      <div className="landing-container">
        <p className="landing-eyebrow"><span className="landing-blue-dot" aria-hidden="true" />{t("A knowledge workspace for startup teams")}</p>
        <h1>{t("Your startup’s knowledge,")}{" "}<span>{t("ready for the next decision.")}</span></h1>
        <div className="landing-hero-summary">
          <p className="landing-hero-copy">{t("Keep notes, links, and research in one Vault. When you run Analyze, Flare surfaces connections with links to the sources behind them.")}</p>
          <div className="landing-hero-action-group">
            <Link className="landing-button landing-button-primary" href="/register">{t("Create a workspace")}<span aria-hidden="true">↗</span></Link>
            <a className="landing-text-link" href="#demo">{t("Explore the preview")}<span aria-hidden="true">↓</span></a>
          </div>
        </div>
        <p className="landing-caption">{t("Early access · Bring your own startup context")}</p>

        <div className="landing-preview" id="demo">
          <div className="landing-preview-caption"><span>{t("PRODUCT PREVIEW")}</span><span>{t("Sample data · Try the tabs, filters, and evidence")}</span></div>
          <div className="landing-demo">
            <div className="landing-demo-topbar">
              <div className="landing-demo-brand"><BrandMark size={20} /><span>Flare</span><span className="landing-demo-divider" aria-hidden="true">/</span><span>{t("Sample workspace")}</span></div>
              <span className="landing-demo-label">{t("Interactive example")}</span>
            </div>
            <div className="landing-demo-layout">
              <aside className="landing-demo-sidebar">
                <div className="landing-demo-tabs" role="tablist" aria-label={t("Product preview")}>
                  {demoTabs.map((tab) => <button key={tab} id={`landing-tab-${tab}`} role="tab" aria-selected={demoTab === tab}
                    aria-controls="landing-sample-panel" tabIndex={demoTab === tab ? 0 : -1} onKeyDown={moveTab}
                    className={demoTab === tab ? "active" : ""} type="button" onClick={() => setDemoTab(tab)}>
                    <span aria-hidden="true">{tab === "capture" ? "＋" : tab === "vault" ? "□" : "✧"}</span>
                    {tab === "capture" ? t("Capture") : tab === "vault" ? t("vault") : t("flares")}
                  </button>)}
                </div>
                <p className="landing-demo-sidebar-note">{t("Your context.")}<br />{t("Your next move.")}</p>
              </aside>
              <div className="landing-demo-body" id="landing-sample-panel" key={demoTab} role="tabpanel" aria-labelledby={`landing-tab-${demoTab}`} tabIndex={0}>
                {demoTab === "insights" && <>
                  <div className="landing-demo-header"><div><p className="landing-demo-kicker">{t("ANALYSIS EXAMPLE")}</p><h2>{t("A connection worth checking.")}</h2></div><Spark size={25} /></div>
                  <div className="landing-filters" role="group" aria-label={t("Insight filters")}>
                    {(["All", "Decisions", "Risks", "Patterns"] as const).map((item) => <button key={item} type="button" aria-pressed={filter === item}
                      className={filter === item ? "active" : ""} onClick={() => selectFilter(item)}>{t(item)}</button>)}
                  </div>
                  <div className="landing-insight-layout">
                    <article className="landing-demo-insight">
                      <p className="landing-signal"><Spark size={14} />{sample.tag}</p>
                      <h3>{sample.title}</h3><p>{sample.body}</p>
                      <button className="landing-evidence-button" type="button" aria-expanded={insightOpen} aria-controls="landing-evidence"
                        onClick={() => setInsightOpen((open) => !open)}><span>{t("2 supporting sources")}</span><span>{insightOpen ? t("Hide evidence ↑") : t("Open evidence ↓")}</span></button>
                      {insightOpen && <div className="landing-evidence" id="landing-evidence">
                        {sample.sources.map((source) => <blockquote key={source.title}><cite>{source.title}</cite><p>{source.quote}</p></blockquote>)}
                      </div>}
                    </article>
                    <aside className="landing-sample-sources" aria-label={t("Sources in this example")}>
                      <p className="landing-demo-kicker">{t("FROM YOUR VAULT")}</p>
                      {sample.sources.map((source) => <div className="landing-sample-source" key={source.title}><span className="landing-file-symbol" aria-hidden="true">↗</span><div><strong>{source.title}</strong><span>{source.kind}</span></div></div>)}
                      <p className="landing-sources-note">{t("An insight is a starting point. The sources help you judge it.")}</p>
                    </aside>
                  </div>
                  {filter === "All" && <div className="landing-other-signals">
                    {samples.slice(1).map((entry) => <button type="button" key={entry.category} onClick={() => selectFilter(entry.category)}><span>{t(entry.category)}</span><strong>{entry.title}</strong><span aria-hidden="true">↗</span></button>)}
                  </div>}
                </>}
                {demoTab === "capture" && <div className="landing-capture-panel">
                  <p className="landing-demo-kicker">{t("CAPTURE EXAMPLE")}</p><h2>{t("Keep the decision with its context.")}</h2>
                  <div className="landing-capture-note"><p className="landing-note-title">{t("Pricing note")}</p><p>{t("Keep the self-serve plan at $49 until activation improves. Enterprise requests can go through a founder-led pilot.")}</p><span>{t("A note you could save to your Vault")}</span></div>
                  <button className="landing-button landing-button-primary" type="button" onClick={() => setDemoTab("vault")}>{t("Preview in Vault")}<span aria-hidden="true">→</span></button>
                </div>}
                {demoTab === "vault" && <div className="landing-vault-panel">
                  <div className="landing-demo-header"><div><p className="landing-demo-kicker">{t("VAULT EXAMPLE")}</p><h2>{t("The context stays close.")}</h2></div><span className="landing-demo-label">{t("Saved context")}</span></div>
                  <div className="landing-vault-list">
                    <article><span className="landing-file-symbol" aria-hidden="true">□</span><div><span>{t("Decision")}</span><h3>{t("Pricing note")}</h3></div></article>
                    <article><span className="landing-file-symbol" aria-hidden="true">□</span><div><span>{t("Planning")}</span><h3>{t("Pricing proposal")}</h3></div></article>
                    <article><span className="landing-file-symbol" aria-hidden="true">□</span><div><span>{t("Interview")}</span><h3>{t("Customer interview — Northstar")}</h3></div></article>
                  </div>
                  <div className="landing-vault-action"><p>{t("Saving context does not start an analysis. You choose when to run it.")}</p><button className="landing-button landing-button-primary" type="button" onClick={() => { setDemoTab("insights"); selectFilter("Decisions"); }}>{t("Analyze sample")}<Spark size={15} /></button></div>
                </div>}
              </div>
            </div>
          </div>
          <p className="landing-preview-footnote">{t("This preview uses sample data. Explore it without changing a workspace.")}</p>
        </div>
      </div>
    </section>

    <section className="landing-section landing-workflow" id="how-it-works">
      <div className="landing-container">
        <div className="landing-section-heading"><p className="landing-section-number">{t("01 / THE WORKFLOW")}</p><div><h2>{t("Keep the context. Then put it to work.")}</h2><p>{t("A small habit for the decisions that deserve a little more context.")}</p></div></div>
        <div className="landing-steps">
          <article><span className="landing-step-number">01</span><h3>{t("Bring it together")}</h3><p>{t("Capture a note, save a link, paste text, or import the notes you already have.")}</p></article>
          <article><span className="landing-step-number">02</span><h3>{t("Choose when to Analyze")}</h3><p>{t("Run Analyze when you want to compare saved context and look for useful connections.")}</p></article>
          <article><span className="landing-step-number">03</span><h3>{t("Follow the evidence")}</h3><p>{t("Open the supporting sources, check the context, and decide what to do next.")}</p></article>
        </div>
      </div>
    </section>

    <section className="landing-section landing-import-section" id="sources">
      <div className="landing-container landing-import-grid">
        <div><p className="landing-section-number">{t("02 / YOUR SOURCES")}</p><h2>{t("Start with what you already know.")}</h2><p className="landing-section-copy">{t("Your notes do not need a fresh start. Bring a snapshot from Notion or Obsidian, then keep adding context as work moves on.")}</p><Link className="landing-text-link" href="/register">{t("Build your Vault")}<span aria-hidden="true">↗</span></Link></div>
        <div className="landing-source-options">
          <div className="landing-source-option"><span className="landing-source-initial" aria-hidden="true">{t("Notion").slice(0, 1)}</span><div><h3>{t("Notion")}</h3><p>{t("Import a Markdown and CSV ZIP export.")}</p></div><span className="landing-source-method">{t("ZIP snapshot")}</span></div>
          <div className="landing-source-option"><span className="landing-source-initial" aria-hidden="true">{t("Obsidian").slice(0, 1)}</span><div><h3>{t("Obsidian")}</h3><p>{t("Import a ZIP of your notes or project folder.")}</p></div><span className="landing-source-method">{t("ZIP snapshot")}</span></div>
          <div className="landing-source-option"><span className="landing-source-initial" aria-hidden="true">＋</span><div><h3>{t("Notes, links, and text")}</h3><p>{t("Save the small details before they disappear.")}</p></div><span className="landing-source-method">{t("Quick capture")}</span></div>
          <p className="landing-import-note">{t("ZIP imports are one-time copies. Later changes in Notion or Obsidian are not synced automatically.")}</p>
        </div>
      </div>
    </section>

    <section className="landing-section landing-principles" id="why-flare">
      <div className="landing-container">
        <div className="landing-section-heading"><p className="landing-section-number">{t("03 / THE PRINCIPLE")}</p><h2>{t("A useful connection should show where it came from.")}</h2></div>
        <div className="landing-principle-list">
          <article><span aria-hidden="true">↗</span><h3>{t("Go back to the source")}</h3><p>{t("Flares link to supporting context so you can read beyond the summary.")}</p></article>
          <article><span aria-hidden="true">＋</span><h3>{t("Keep building your Vault")}</h3><p>{t("Keep useful notes and imported records together for the next question.")}</p></article>
          <article><Spark size={20} /><h3>{t("Stay in control of Analyze")}</h3><p>{t("Capture and import first. Start analysis when you are ready to review it.")}</p></article>
        </div>
      </div>
    </section>

    <section className="landing-final-cta"><div className="landing-container landing-final-grid"><div><p className="landing-final-kicker">{t("THE NEXT DECISION STARTS HERE")}</p><h2>{t("Give your startup a memory.")}</h2><p>{t("Start with a note. Keep the context that makes it useful.")}</p></div><Link className="landing-button landing-button-light" href="/register">{t("Create a workspace")}<span aria-hidden="true">↗</span></Link></div></section>
    <footer className="landing-footer"><div className="landing-container"><Link className="landing-brand" href="#top" aria-label={t("Back to top")}><BrandMark size={26} /><span>Flare</span></Link><span>© 2026 Flare</span><nav aria-label={t("Legal and account links")}><Link href="/privacy">{t("Privacy")}</Link><Link href="/terms">{t("Terms")}</Link><Link href="/login">{t("Sign in")}</Link></nav></div></footer>
  </main>;
}
