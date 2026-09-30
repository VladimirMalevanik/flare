"use client";
import { useI18n } from "@/i18n/provider";
import { LanguageSelector } from "@/components/language-selector";
import Link from "next/link";

import { BrandMark } from "@/components/brand-mark";

const RELEASES_URL = "https://github.com/VladimirMalevanik/flare/releases/latest";
const APPLE_SILICON_URL = `${RELEASES_URL}/download/Flare-macOS-arm64.dmg`;
const INTEL_URL = `${RELEASES_URL}/download/Flare-macOS-x64.dmg`;



export default function DownloadPage() {
  const { t } = useI18n();

  return (
    <main className="download-page">
      <header className="download-nav-shell">
        <div className="download-container download-nav">
          <Link className="landing-brand" href="/" aria-label={t("Flare home")}>
            <BrandMark size={28} />
            <span>Flare</span>
          </Link>
          <nav aria-label={t("Download navigation")}>
            <LanguageSelector />
            <Link href="/">{t("Website")}</Link>
            <Link href="/login">{t("Sign in")}</Link>
          </nav>
        </div>
      </header>

      <section className="download-hero">
        <div className="download-container">
          <p className="landing-eyebrow">{t("Flare for macOS")}</p>
          <h1>{t("Your startup memory, one click away.")}</h1>
          <p className="download-lead">
            {t("Capture notes, review evidence, and keep your Flare workspace close without leaving a browser tab open.")}</p>

          <div className="download-options">
            <article className="download-card download-card-featured">
              <span className="download-badge">{t("Recommended for most Macs")}</span>
              <div className="download-card-icon" aria-hidden="true">M</div>
              <p className="download-architecture">Apple silicon</p>
              <h2>{t("Macs with an M-series chip")}</h2>
              <p>
                {t("Choose this version for a Mac with an Apple M1, M2, M3, M4, or newer chip.")}</p>
              <a className="landing-button landing-button-primary" href={APPLE_SILICON_URL}>
                {t("Download for Apple silicon")}{" "}<span aria-hidden="true">↓</span>
              </a>
              <small>DMG · arm64</small>
            </article>

            <article className="download-card">
              <span className="download-badge download-badge-neutral">{t("Legacy Macs")}</span>
              <div className="download-card-icon download-card-icon-neutral" aria-hidden="true">i</div>
              <p className="download-architecture">Intel</p>
              <h2>{t("Macs with an Intel processor")}</h2>
              <p>
                {t("Choose this version if About This Mac lists an Intel processor.")}</p>
              <a className="landing-button landing-button-secondary" href={INTEL_URL}>
                {t("Download for Intel")}{" "}<span aria-hidden="true">↓</span>
              </a>
              <small>DMG · x64</small>
            </article>
          </div>

          <p className="download-release-note">
            {t("Downloads come from Flare's public GitHub Releases. If a direct download is temporarily unavailable, open the")}{` `}
            <a href={RELEASES_URL}>{t("latest release")}</a>.
          </p>
        </div>
      </section>

      <section className="download-install">
        <div className="download-container download-install-grid">
          <div>
            <p className="landing-section-number">{t("INSTALLATION")}</p>
            <h2>{t("From download to Flare in three steps.")}</h2>
          </div>
          <ol>
            <li>
              <span>1</span>
              <div><strong>{t("Open the DMG")}</strong><p>{t("Use the file that matches your Mac's processor.")}</p></div>
            </li>
            <li>
              <span>2</span>
              <div><strong>{t("Move Flare to Applications")}</strong><p>{t("Drag the Flare icon into the Applications folder.")}</p></div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>{t("Approve the early-access build")}</strong>
                <p>
                  {t("If macOS blocks the first launch, open System Settings → Privacy & Security and choose Open Anyway.")}</p>
              </div>
            </li>
          </ol>
        </div>
      </section>

      <section className="download-disclosure">
        <div className="download-container">
          <BrandMark className="download-disclosure-mark" size={34} />
          <h2>{t("An honest early-access build.")}</h2>
          <p>
            {t("This release uses an ad-hoc signature and is not yet notarized with an Apple Developer ID, so macOS shows an extra confirmation. The app requires an internet connection and uses the same Flare account, cloud service, and")}{` `}
            <Link href="/privacy">{t("Privacy Policy")}</Link> {" "}{t("as the website.")}</p>
        </div>
      </section>

      <footer className="download-footer">
        <div className="download-container">
          <span>© 2026 Flare</span>
          <nav aria-label={t("Download footer")}>
            <Link href="/privacy">{t("Privacy")}</Link>
            <Link href="/terms">{t("Terms")}</Link>
            <Link href="/">{t("Back to website")}</Link>
          </nav>
        </div>
      </footer>
    </main>
  );
}
