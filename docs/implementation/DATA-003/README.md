# DATA-003 — five connected context sources

Owner delegated the choice and implementation of five priorities for US startup
teams on 2026-10-12. The selected product priorities are Slack, Gmail, Google Drive,
Notion and GitHub. This is a reasoned Flare workflow choice, not a measured US
market-share ranking. Telegram, reviews and other sources remain outside this task.

## Contract locked before implementation

- Slack: selected public channels the bot can access; plain message text, author
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
