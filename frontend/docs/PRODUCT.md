# Product

Flare MVP is a calm personal knowledge workspace. Its flow is:

**Capture → Store → Retrieve → Surface grounded insights**

- **Insights** is the home view: a short conclusion, its explanation, and supporting evidence linked to source items.
- **Vault** is where a person searches, filters, reads, and connects source material.
- **Sources** connects one GitHub repository through a GitHub App and shows other integrations as demo or coming soon. GitHub activity is not ingested yet.
- **Settings** holds local profile, appearance, notification, and privacy preferences.

Every page shares a floating capture bar. In API mode, Notes and bounded UTF-8 CSV,
TXT, and Markdown imports persist through the backend and enqueue analysis. URL,
file metadata, and audio metadata can be stored as sources, but URL fetching, binary
upload, and durable transcript persistence are not connected. Voice can record a
browser Blob and has an isolated Whisper provider boundary.

The MVP deliberately does not add folders, collections, knowledge graphs, export
workflows, or next-step automation. Its analytics endpoint records only bounded,
allowlisted workflow events and exposes an aggregate workspace summary.
