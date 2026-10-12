# DATA-003 — five connected context sources

Owner delegated the choice and implementation of five priorities for US startup
teams on 2026-10-12. The selected product priorities are Slack, Gmail, Google Drive,
Notion and GitHub. This is a reasoned Flare workflow choice, not a measured US
market-share ranking. Telegram, reviews and other sources remain outside this task.

## Contract locked before implementation

- Slack: selected public channels the authorizing user belongs to; plain message text, author
  and timestamps. No private conversations, automatic joining or message sending.
- Gmail: selected labels and their messages, with sender/subject/date and plain
  text. No mail modifications, outbound messages or attachment ingestion.
- Drive: explicitly selected Google Docs and supported plain text files. No
  crawling a whole Drive by default, spreadsheets, slides, binaries or attachments.
- Notion: selected accessible pages and bounded text blocks. Existing ZIP import
  remains available. No page writes or indiscriminate workspace crawling.
- GitHub: the repository explicitly selected through the existing GitHub App
  authorization, with README, issues and PR summaries. No full codebase ingestion,
  code writes or broad installation access tokens.

Connections import selected snapshots into the existing shared workspace Vault.
The connector owner must explicitly confirm that selected content will be visible
to workspace members. Only that owner can inspect/select private remote resources
or change the selection; permitted workspace administrators can stop a connection.
Tokens never reach browsers. Disconnect stops future sync and destroys stored
credentials; already imported workspace snapshots are retained, with their dated
provenance. A new consent/connection is required to resume. Source permissions and
membership are rechecked before fetching and publishing; connection revisions and
leases prevent late cancelled/revoked jobs publishing content. Locally edited or
deleted documents are never silently overwritten or resurrected by source sync.

Use one common durable job/cursor mechanism with bounded network responses,
request count, text size, pagination, attempts and retry delays. Provider429 must
respect Retry-After, including Slack's restrictive commercial-app history limits.
Import uses immutable document versions and original source links. Same external
record/content never creates duplicate documents. Source sync performs no AI calls
and never requests Analyze; the existing scheduled-only daily pipeline consumes
the latest saved context under its existing limits and snapshot timing.

## Design lock

Preserve the current Sources cards, palette, icons, button styles, status and
accessible dialogs. Add a real connect/select/sync/disconnect flow, visible last
sync/result and recoverable errors. Distinguish not enabled, connected but not
selected, syncing, partial result and authentication lost. Never render connected
or imported success from static catalog data. Existing ZIP controls remain.

## Evidence

- Glean's connector catalog covers these five sources and documents provider
  authorization/content/permission handling:
  https://docs.glean.com/connectors/ and
  https://docs.glean.com/connectors/about
- Slack describes small-team project/customer workflows:
  https://slack.com/solutions/small-business
- Notion has a startup-specific program:
  https://www.notion.com/help/notion-for-startups
- Provider API contracts are checked with Context7 and official documentation.
  Gmail full read access is a restricted scope; production provider registration
  and review remain release-owner work, not claimed as completed by code tests.

## Delivery gates

Five adapters, authorization and isolation regressions, real PostgreSQL queue /
publication invariants, frontend states, full existing suites, production build
and synthetic browser flows must pass before handoff. No new runtime dependencies
or paid resources. Existing crypto support supplied by PyJWT's crypto extra is
reused for authenticated server-side credential encryption. Migration0023 is
source-only until the release owner deploys it. Provider app credentials, signing /
encryption keys, Google verification, GitHub read permissions, worker deployment
and real-account smoke are explicit Vova activation gates. No existing private
credentials, real customer content or production configuration is inspected here.


## Implemented contract and boundaries

- Slack: OAuth user token with channels:read and channels:history. Public channels the actor belongs to; recent messages and thread replies, per-message links. No private channels, DMs, joins or sends. History/replies pages <=15, queued steps separated by >=60 seconds; actual 429 Retry-After retained.
- Gmail: selected labels, recent window (30 days by default), full MIME text/HTML-to-text, message URL, sender and date. No attachments, sends or modifications. Each cycle rescans the bounded window, so label changes are observed; overlapping labels deduplicate by account/message. This is not a complete historical mailbox archive.
- Google Drive: selected Google Docs exported as text, and UTF-8 TXT/Markdown/CSV. No binary attachments, spreadsheets, slides or recursive folders.
- Notion: selected accessible pages, nested text blocks, checkpointed child pagination, current API version. No file downloads or automatic child-page selection. Traversal currently caps text at 8 KB to keep resumable encrypted checkpoints bounded; oversized pages are counted as skipped.
- GitHub: existing authorized selected App repository, repository-id-limited temporary read token, README plus recent issue/PR summaries. No whole-codebase crawl, comments, reviews or writes.

Per-resource incremental checkpoints continue across bounded batches; a completed scan resets for the next cycle. Remote changes create immutable Vault versions. Local edits and deletions are preserved and counted as conflicts. No analysis jobs are enqueued by this worker.

## Release activation (Vova)

Source implementation is separate from live authorization. Do not call these five connections live until the following are configured and tested with consenting test accounts:

1. Deploy migration 0023 before the API/worker version expecting schema 0023. Take a backup and keep old workers paused during migration. Run full self-managed/Yandex checks for the exact source head.
2. Configure the tracked SOURCE_* settings in the release secret manager (never in frontend). SOURCE_PUBLIC_API_URL and SOURCE_FRONTEND_URL must share the authenticated public origin. Frontend URL is the origin, e.g. https://flare4u.tech; API URL includes the existing /api rewrite prefix. Callback is /api/integrations/sources/{provider}/callback. Set provider callbacks exactly in the provider apps.
3. Create/approve Slack read-only public channel user scopes, Notion public read-content integration and Google offline OAuth app. Request gmail.readonly / drive.readonly only (Drive also openid/email for identity). Restricted Google scopes may require verification and an assessment for public server-side storage; do not assume the unverified test app is production-ready. Respect testing-mode token lifetimes. App names/privacy policy/support/contact/domain settings are release-owner decisions.
4. Grant the existing GitHub App contents/issues/pull_requests read permissions for the selected repository; account owners approve any permission upgrade. Existing App authorization alone does not mean content access is granted.
5. Generate a Fernet key with the existing cryptography runtime; put it in SOURCE_TOKEN_KEYS. Rotation: new key first, previous key(s) retained until saved credentials and all pending cursors/states are renewed. Losing keys requires reconnecting sources. Never send keys in chat or commit them.
6. Start a separate worker with the restricted WORKER_DATABASE_URL: python -m app.workers.source_worker. It has no fallback to the app/admin DB role. Configure the same source settings/keys on worker and API. Keep keys/configuration aligned. Worker heartbeat enables Sync now; no heartbeat means honest unavailable status.
7. Connect each provider as a consenting workspace editor/owner, choose only test resources, explicitly accept sharing, wait for sync, verify Vault text and original links, repeat sync for deduplication, cancel a queued run, disconnect and verify no later publication. Verify another workspace/user cannot browse the connection's private candidates or tokens. Confirm scheduled Analyze works without spending any AI calls during sync.
8. Only then set SOURCES_ENABLED=true for the intended environment. No production deployment or OAuth consent to personal accounts was performed in this task.

Disconnect clears stored authorization and pending states and stops future sync. Existing Vault snapshots remain shared by design; deleting saved context is a separate Vault action. Flare does not mirror external per-person ACLs or automatically erase historical evidence on remote deletion.
