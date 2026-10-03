"use client";
import { useI18n } from "@/i18n/provider";
import Link from "next/link";

type ImportGuidePageProps = {
  source: "Notion" | "Obsidian" | "Evernote";
  preparation: string;
};

export function ImportGuidePage({ source, preparation }: ImportGuidePageProps) {
  const { t, label } = useI18n();
  const zipImport = source === "Notion" || source === "Obsidian";

  return (
    <section className="page settings-page">
      <header className="page-heading">
        <p className="eyebrow">{t("Import guide")}</p>
        <h1>{t("importGuideTitle", { source })}</h1>
        <p>{t(zipImport ? "zipGuideFormats" : "importGuideFormats")}</p>
      </header>

      <section className="card settings-section">
        <header>
          <h2>{t(zipImport ? "Prepare your ZIP" : "Prepare your file")}</h2>
          <p className="muted meta">{t(zipImport ? "One-time snapshot import. Changes in the original tool are not synchronized." : "Keep each upload focused enough to stay within the current size limit.")}</p>
        </header>
        <ol className="import-guide-steps">
          {zipImport ? (
            <>
              <li>{t(source === "Notion" ? "Export your Notion pages as Markdown and CSV in one ZIP." : "Create one ZIP snapshot of your Obsidian vault or project folder.")}</li>
              <li>{t("Include .md, .markdown, .txt, and .csv files. Unsupported formats are skipped and listed in the import report; package safety checks still apply.")}</li>
              <li>{t("zipGuideUpload", { source })}</li>
              <li>{t("Processing runs asynchronously. Follow progress in Sources and open the import report to review imported or skipped files.")}</li>
              <li>{t("Imported sources appear together in Vault after the package is published. Import does not start Analyze automatically.")}</li>
            </>
          ) : (
            <>
              <li>{label(preparation)}</li>
              <li>{t("Choose a Markdown, text, or CSV file no larger than 200 KB.")}</li>
              <li>{t("Open Capture in Flare, attach that one file, review it, and submit it.")}</li>
            </>
          )}
        </ol>
        <p className="muted meta">
          {t("Provider-specific export screenshots and click-by-click instructions are pending validation.")}</p>
        <div className="form-actions">
          <Link className="button" href="/settings">{t("Back to Settings")}</Link>
          <Link className="button primary" href={zipImport ? "/sources" : "/dashboard"}>{t(zipImport ? "Open Sources" : "Return to workspace")}</Link>
        </div>
      </section>
    </section>
  );
}
