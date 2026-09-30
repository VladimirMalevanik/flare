"use client";
import { useI18n } from "@/i18n/provider";
import Link from "next/link";

type ImportGuidePageProps = {
  source: "Notion" | "Obsidian" | "Evernote";
  preparation: string;
};

export function ImportGuidePage({ source, preparation }: ImportGuidePageProps) {
  const { t, label } = useI18n();

  return (
    <section className="page settings-page">
      <header className="page-heading">
        <p className="eyebrow">{t("Import guide")}</p>
        <h1>{t("importGuideTitle", { source })}</h1>
        <p>{t("importGuideFormats")}</p>
      </header>

      <section className="card settings-section">
        <header>
          <h2>{t("Prepare your file")}</h2>
          <p className="muted meta">{t("Keep each upload focused enough to stay within the current size limit.")}</p>
        </header>
        <ol className="import-guide-steps">
          <li>{label(preparation)}</li>
          <li>{t("Choose a Markdown, text, or CSV file no larger than 200 KB.")}</li>
          <li>{t("Open Capture in Flare, attach that one file, review it, and submit it.")}</li>
        </ol>
        <p className="muted meta">
          {t("Provider-specific export screenshots and click-by-click instructions are pending validation.")}</p>
        <div className="form-actions">
          <Link className="button" href="/settings">{t("Back to Settings")}</Link>
          <Link className="button primary" href="/dashboard">{t("Return to workspace")}</Link>
        </div>
      </section>
    </section>
  );
}
