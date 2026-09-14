# Product

Flare MVP is a calm personal knowledge workspace. Its flow is:

**Capture → Store → Retrieve → Surface grounded insights**

- **Insights** is the home view: a short conclusion, its explanation, and supporting evidence linked to source items.
- **Vault** is where a person searches, filters, reads, and connects source material.
- **Sources** connects one GitHub repository through a GitHub App and shows other integrations as demo or coming soon. GitHub activity is not ingested yet.
- **Settings** holds local preferences and the persistent workspace daily-insight time.

Every page shares a floating capture bar. In API mode, Notes and bounded UTF-8 CSV,
TXT, and Markdown imports persist immediately through the backend. Saving or editing
never starts AI by itself. URL records can be stored without fetching them. Binary
file upload and the final voice-provider handoff are not connected. Voice records a
bounded browser Blob; media inspection and transcript persistence are prepared, and
the UI never invents or saves a demo transcript.

Owners and editors can run one insight per workspace local day, either manually or
at the saved IANA-timezone schedule. Flare freezes the latest supported database
versions 30 minutes before a scheduled run. GitHub content is excluded until its
ingestion implementation exists; the UI states that limitation directly.

The MVP deliberately does not add folders, collections, knowledge graphs, export
workflows, or next-step automation. Its analytics endpoint records only bounded,
allowlisted workflow events and exposes an aggregate workspace summary.
