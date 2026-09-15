# Frontend data contract

These are frontend domain contracts, not a prescribed backend implementation. An adapter may map any backend DTO into these shapes.

```ts
type ItemType = "note" | "url" | "file" | "audio";
type ItemStatus = "ready" | "processing" | "error";
interface ExtractedFact { id: string; text: string }
interface Item {
  id: string; type: ItemType; title: string; content: string;
  sourceUrl?: string; fileName?: string; fileSize?: number;
  status: ItemStatus; createdAt: string; updatedAt: string;
  currentVersionId: string; versionNumber: number;
  extractedFacts: ExtractedFact[]; relatedItemIds: string[];
}
interface Evidence { itemId: string; sourceTitle: string; sourceType: ItemType; excerpt: string; sourceUrl?: string | null }
type FlareType = "Reminder" | "Warning" | "Recommendation";
interface Insight {
  id: string; type: FlareType; title: string; statement: string; action: string | null;
  reason: string; evidence: Evidence[]; createdAt: string;
}
```

Logical operations expected by the interface:

- `listItems({ query?, type?, limit?, beforeUpdatedAt?, beforeId? }) → Item[]`; оба cursor-поля передаются вместе
- `getItem(id) → Item | null`
- `createItem({ type, title?, content?, sourceUrl?, fileName?, fileSize?, status? }) → Item`
- `updateItem(id, { expectedCurrentVersionId, title, content, ...typeFields }) → Item`
- `importTextFile({ format: "csv" | "txt" | "md", fileName, fileType?, fileSize, content }) → ImportResult`
- `deleteItem(id) → void`
- `listInsights() → Insight[]`
- `getInsight(id) → Insight | null`
- `listSources() → Source[]`
- `saveSource(source) → Source`
- `getGitHubConnection() → GitHubConnection`
- `startGitHubConnection() → authorizationUrl`
- `listGitHubRepositories() → GitHubRepository[]`
- `selectGitHubRepository(repositoryId) → GitHubConnection`
- `disconnectGitHub() → void`
- `getAnalysisSchedule() → AnalysisSchedule`
- `updateAnalysisSchedule({ enabled, emailNotificationsEnabled, timezone, localTime }) → AnalysisSchedule`
- `getDailyAnalysisStatus() → DailyAnalysisStatus`

Optional Item display fields remain `category`, `sourceLabel`, `author`, and
`fileType`. The internal names `Insight`, `listInsights`, and `getInsight` remain;
the public Flare types are Reminder, Warning and Recommendation. Legacy Discovery
records are not converted into Recommendations.

The REST adapter uses `GET /items`, `GET /items/:id`, `POST /items`,
`PATCH /items/:id`, `DELETE /items/:id`, and `POST /imports`. Every real edit
publishes a new immutable version; the optimistic version token prevents lost
updates. Text imports are bounded to CSV, TXT
and Markdown and send text rather than a browser-local file path. The server
stores the source as an ordinary Item, preserving its chunks for citations.
Sources can connect a GitHub App installation and persist a selected repository;
copying repository contents is not implemented yet. Flares never use a mock in
API mode.

## Flares (Block 4)

- `GET /flares?limit=50`: authenticated current workspace, limit 1–100;
  newest first (`created_at DESC, id DESC`); `[]` is valid.
- `GET /flares/{id}`: the same DTO; missing, foreign and deleted-evidence records
  return the same 404. `getInsight` maps only 404 to null; other errors propagate.
- Both responses use `Cache-Control: no-store`. Browser requests include cookies.
- DTO fields match `Insight` above; evidence `sourceUrl` is nullable on the wire
  and remains nullable/optional in the frontend. Quotes navigate to `/vault?item={itemId}`,
  where the source is loaded through `GET /items/{itemId}`.
- Any deleted supporting document hides the entire Flare. Untyped legacy insights
  are excluded. Internal run IDs, raw responses, errors and reasoning are absent.
- Saving, importing, or editing a source never starts AI. Manual Analyze and the
  workspace daily schedule select and pin bounded context separately.

## Analyze (Block 5)

`POST /analyze` requires a session cookie, allowed Origin, owner/editor role,
`Idempotency-Key: UUID` and exactly `{}` as JSON. Identity and sources are server-owned.
It returns 202 while pending/processing; replay of a terminal run returns 200.
`GET /analysis-runs/{id}` returns 200 for any current member of the same workspace,
or 404 for an unknown/foreign run. Both responses are no-store:

```ts
{ id: string; status: "pending" | "processing" | "completed" | "failed";
  stage: "analysis" | "flare_generation" | "completed" | "failed";
  selectedChunkCount: number; flareIds: string[]; error: string | null }
```

Completion includes Flare generation, including valid empty output. Errors are safe
codes only. Polling backs off from 1 to 10 seconds, stops after 40 polls or five
minutes, and cancels on navigation. Check status resumes an existing run; retry
after terminal failure uses a new key. An uncertain POST retries the same key.
API mode never substitutes demo results.

The database permits one analysis cycle per workspace local calendar date. Manual
Analyze and the saved schedule share that slot; another key returns `409 daily_limit`.
`GET/PUT /analysis-schedule` stores `enabled`, `emailNotificationsEnabled`, an IANA
`timezone`, and `localTime`. Email defaults on and is sent only after a successful
scheduled run creates at least one Flare; the message contains titles and links only.
`GET /analysis/daily-status` returns the cycle/run state and T-30 snapshot status.
If a schedule is saved after today’s preparation deadline, its first run is tomorrow.
Terminal failure keeps the slot consumed; bounded automatic retries remain in the
same cycle. GitHub reports `ingestionSupported: false` until repository content
ingestion is implemented.

## Workspace export

`GET /export` requires a verified workspace owner and returns a no-store ZIP download.
It contains active current Notes/imported text and visible Flares as Markdown plus a
machine-readable JSON copy. The server selects through the authenticated workspace
transaction and exports only allowlisted source metadata; auth data, credentials,
provider secrets, queue state, and other workspaces are absent.

## Analytics

`POST /analytics/events` accepts only browser interaction events used by this UI:
`capture_started`, `capture_submitted`, `capture_file_attached`,
`capture_voice_started`, `capture_voice_stopped`, `item_viewed`, `flare_viewed`,
and `screen_opened`. Each event has a fixed target and bounded enum/integer
metadata; note/file text, titles, URLs, filenames, OAuth values and provider
payloads are not valid analytics fields. Server outcomes such as item creation,
imports, analysis, scheduling, queue maintenance and GitHub authorization cannot
be submitted through the client endpoint. Any workspace member, including a
viewer, may record these UI interactions under their authenticated actor ID.
The server verifies referenced item/Flare IDs inside that workspace and ignores
events beyond 600 accepted browser events per actor in a rolling hour. These
best-effort limits never block the product action that the event describes.

Flare views are counted in the browser when the evidence panel opens. The detail
GET does not record another view, and the same panel load is deduplicated. Closing
and reopening the panel records a new view. Capture opening is emitted by the
shared Capture component, including when opened from the empty Flares state.

## Authentication (Block 1)

Browser requests use same-origin `/api`, rewritten to FastAPI; server session
bootstrap uses `API_INTERNAL_URL`. Set that URL at both build and runtime.
`POST /auth/register` accepts
`{email, password, name, termsAccepted: true, privacyAccepted: true}`. Both
acceptance fields are required and migration `0017` records the current Terms and
Privacy versions atomically with the account. Registration may set a limited
HttpOnly session while email verification is pending. `POST /auth/login`
accepts `{email, password}` and returns the stable code
`email_verification_required` for a correct but unverified account.
`POST /auth/verify-email` consumes one token; `POST /auth/resend-verification`
always returns a neutral 202. `GET /auth/me` returns
`{user: {id, email, name, emailVerified}, workspace: {id, name, role}}`;
`POST /auth/logout` revokes the session. Prefix these paths with `/api` in browsers.
State-changing requests require an allowed Origin and `credentials: "include"`.
401 redirects to login; 403 represents denied membership/role or Origin.
Items, Flares and Analyze require a verified session. Identity comes from the backend, never
localStorage or arbitrary headers. One initial workspace is supported; there
is no switching UI. Settings displays server profile fields read-only.
