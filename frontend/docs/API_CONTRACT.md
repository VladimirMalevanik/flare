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
interface Evidence { itemId: string; sourceTitle: string; sourceType: ItemType; excerpt: string }
interface Insight { id: string; title: string; summary: string; explanation: string; evidence: Evidence[]; createdAt: string }
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

Cupertino additions are optional on existing item/insight records: `Item.category` (discussion, pull-request, note, voice), `sourceLabel`, `author`, and `fileType`; `Insight.kind` (Contradiction, Repeated Problem, Hidden Connection, Unresolved Question) and `detailTitle`. Old locally captured items continue to work without these fields. `Source` contains `id`, `name`, `scope`, `description`, `channels`, `status` (connected, syncing, disconnected), and a human-readable `updated` label. The source adapter must replace demo connection behavior with the real authorization/sync flow during integration.

The current REST adapter uses `GET /items`, `GET /items/:id`, `POST /items`, and `DELETE /items/:id`. The first API slice accepts notes; URL, file, and audio ingestion remain explicit follow-up work. Insights and Sources continue through the mock fallback until their endpoints exist. `POST /items` may later become asynchronous: return an `Item` with `status: "processing"`, then allow the client to refresh or subscribe. Authentication, upload URLs, pagination, and delivery mechanism remain backend concerns.
