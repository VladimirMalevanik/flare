# Frontend data contract

These are frontend domain contracts, not a prescribed backend implementation. An adapter may map any backend DTO into these shapes.

```ts
type ItemType = "note" | "url" | "file" | "audio";
type ItemStatus = "ready" | "processing" | "error";
interface ExtractedFact { id: string; text: string }
interface Item {
  id: string; type: ItemType; title: string; content: string;
  sourceUrl?: string; fileName?: string; fileSize?: number;
  status: ItemStatus; createdAt: string;
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

- `listItems({ query?, type?, limit? }) → Item[]`
- `getItem(id) → Item | null`
- `createItem({ type, title?, content?, sourceUrl?, fileName?, fileSize?, status? }) → Item`
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

Optional Item display fields remain `category`, `sourceLabel`, `author`, and
`fileType`. The internal names `Insight`, `listInsights`, and `getInsight` remain;
the public Flare types are Reminder, Warning and Recommendation. Legacy Discovery
records are not converted into Recommendations.

The REST adapter uses `GET /items`, `GET /items/:id`, `POST /items`, and
`DELETE /items/:id`. Only Note ingestion is implemented. Sources uses the catalog
fallback for non-GitHub cards, while GitHub connection state, repository listing,
selection, and disconnect use `/integrations/github`. GitHub activity ingestion is
not implemented. Flares never use a mock fallback in API mode.

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
- Note saving does not enqueue analysis. Explicit Analyze selects and pins context.

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

## Authentication (Block 1)

Browser requests use same-origin `/api`, rewritten to FastAPI; server session
bootstrap uses `API_INTERNAL_URL`. Set that URL at both build and runtime.
`POST /auth/register` accepts `{email, password, name}` and may set a limited
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
