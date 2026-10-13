# Explicit analysis feedback

Owner report: a friend saved a note and saw no Flare, which looked like a broken product. The cause of that particular live run is unknown; API-005 remains Vova's separate generation investigation.

## Behavior

- Flares reads the exact completed run through the existing authenticated AnalysisRun API. Only a matching, completed receipt with zero `flareIds` produces the visible “No new Flares found” result notice. Overall feed size, note usefulness guesses and browser inference cannot create this notice.
- The message confirms completion and saved Vault notes without declaring the note useless or promising a Flare per note. Older Flares remain available. Nonzero runs show their real new result count.
- Waiting/preparing/running, disabled schedule, failed analysis and no-ready-context states stay distinct. A failed/expired/mismatched result lookup says the receipt is unavailable and retries on the existing status poll; it does not report zero or pipeline failure.
- Exact result transport and parsing are bounded through the existing request helper. Unmount aborts it; late responses cannot replace the view. Completion still refreshes the feed once per run and never starts Analyze.
- Capture's saved confirmation explains that insights follow the project's analysis schedule. The empty feed also explains that saved notes are retained while Flares surface when analysis finds a new signal.
- English and Spanish copy, accessible nonblocking live status, project-bound existing links and both themes use existing Flare tokens/components. No modal, synthetic insights, provider calls, emails or quota changes.

## Reference lock and validation

Existing Flare schedule/status UI and Vault/Team feedback surfaces supply the layout and typography. Refero craft guidance supplies semantic status announcements, inline recovery and readable spacing. Use existing blue/check icon for successful processing, a full-width restrained surface below the feed header and the established save toast. No new design system or dependency.

Frontend and exact-result tests exercise empty/nonempty runs, all incomplete/failure states, lookup failure/mismatched receipt, stale zero notice, ignored abort transport deadline and unmount. Exact CI/artifact/browser evidence is recorded in PR/task handoff. Backend/schema/generator files are unchanged. Main merge does not deploy this UI to Azure.
