import Link from "next/link";

type ImportGuidePageProps = {
  source: "Notion" | "Obsidian" | "Evernote";
  preparation: string;
};

export function ImportGuidePage({ source, preparation }: ImportGuidePageProps) {
  return (
    <section className="page settings-page">
      <header className="page-heading">
        <p className="eyebrow">Import guide</p>
        <h1>Bring {source} content into Flare</h1>
        <p>
          Flare currently accepts one <strong>.md</strong>, <strong>.txt</strong>, or <strong>.csv</strong> file at a time, up to 200 KB.
        </p>
      </header>

      <section className="card settings-section">
        <header>
          <h2>Prepare your file</h2>
          <p className="muted meta">Keep each upload focused enough to stay within the current size limit.</p>
        </header>
        <ol className="import-guide-steps">
          <li>{preparation}</li>
          <li>Choose a Markdown, text, or CSV file no larger than 200 KB.</li>
          <li>Open Capture in Flare, attach that one file, review it, and submit it.</li>
        </ol>
        <p className="muted meta">
          Provider-specific export screenshots and click-by-click instructions are pending validation.
        </p>
        <div className="form-actions">
          <Link className="button" href="/settings">Back to Settings</Link>
          <Link className="button primary" href="/dashboard">Return to workspace</Link>
        </div>
      </section>
    </section>
  );
}
