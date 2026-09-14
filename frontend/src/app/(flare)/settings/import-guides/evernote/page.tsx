import { ImportGuidePage } from "@/features/settings/import-guide-page";

export default function EvernoteImportGuide() {
  return (
    <ImportGuidePage
      source="Evernote"
      preparation="Use Evernote's official export tools, then prepare the content as Markdown, text, or CSV for Flare."
    />
  );
}
