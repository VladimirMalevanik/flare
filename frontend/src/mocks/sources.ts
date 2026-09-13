import type { Source } from "@/lib/data/types";
export const seedSources: Source[] = [
  {
    id: "manual-capture", name: "Manual capture", scope: "Notes, links, and text imports",
    description: "Add project context directly from the Flare orb, including CSV, TXT, and Markdown files.", channels: ["Notes", "Links", "CSV", "TXT", "Markdown"], status: "ready", updated: "Ready to use",
  },
  {
    id: "voice", name: "Voice", scope: "Voice memos",
    description: "Voice transcription and API persistence are planned after MVP.", channels: [], status: "coming-soon", updated: "Coming soon",
  },
  {
    id: "obsidian", name: "Obsidian import", scope: "One-time onboarding import",
    description: "Automatic vault sync is planned. Export Markdown and import it through Add context today.", channels: [], status: "coming-soon", updated: "Coming soon",
  },
  {
    id: "telegram", name: "Telegram", scope: "Project conversations",
    description: "Automatic conversation ingestion is planned after MVP.", channels: [], status: "coming-soon", updated: "Coming soon",
  },
  {
    id: "github", name: "GitHub", scope: "Project activity",
    description: "Automatic project activity ingestion is planned after MVP.", channels: [], status: "coming-soon", updated: "Coming soon",
  },
  {
    id: "gmail",
    name: "Gmail", scope: "Customer email",
    description: "Customer email context is planned after MVP.", channels: [], status: "coming-soon", updated: "Coming soon",
  },
  {
    id: "reviews",
    name: "App Reviews",
    scope: "Apple App Store and Google Play",
    description: "App review context is planned after MVP.",
    channels: [],
    status: "coming-soon",
    updated: "Coming soon",
  },
  {
    id: "notion", name: "Notion", scope: "Workspace notes",
    description: "Automatic workspace imports are planned after MVP.", channels: [], status: "coming-soon", updated: "Coming soon",
  },
  {
    id: "linear", name: "Linear", scope: "Product planning",
    description: "Automatic planning context is planned after MVP.", channels: [], status: "coming-soon", updated: "Coming soon",
  },
];
