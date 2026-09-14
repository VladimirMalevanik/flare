import { ImportGuidePage } from "@/features/settings/import-guide-page";

export default function ObsidianImportGuide() {
  return (
    <ImportGuidePage
      source="Obsidian"
      preparation="Choose a Markdown note from your Obsidian vault, or prepare its content as text or CSV."
    />
  );
}
