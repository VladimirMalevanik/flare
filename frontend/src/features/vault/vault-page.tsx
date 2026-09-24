"use client";
import Link from "next/link";
import type { Route } from "next";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  dataErrorMessage,
  dataProvider,
  type Item,
  type ItemType,
  type UpdateItemInput,
} from "@/lib/data";
import { useWorkspace } from "@/components/workspace-context";
import { useSession } from "@/components/auth-session";
import { Icon, itemIcon } from "@/components/icons";
import { Dialog } from "@/components/dialog";
const PAGE_SIZE = 50;
const PAGE_FETCH_SIZE = PAGE_SIZE + 1;
export function withoutLinkedItem(pathname: string, query: string): string {
  const next = new URLSearchParams(query);
  next.delete("item");
  const queryString = next.toString();
  return queryString ? `${pathname}?${queryString}` : pathname;
}
type VaultFilter = "all" | "note" | "url" | "voice" | "file";
const filters: { id: VaultFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "note", label: "Notes" },
  { id: "url", label: "Links" },
  { id: "voice", label: "Voice" },
  { id: "file", label: "Files" },
];
export function VaultPage() {
  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const session = useSession();
  const { revision, refresh } = useWorkspace();
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Item | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<VaultFilter>("all");
  const [view, setView] = useState("grid");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editSourceUrl, setEditSourceUrl] = useState("");
  const [editError, setEditError] = useState("");
  const listRequest = useRef(0);
  const closedLinkedItem = useRef<string | null>(null);
  const linkedItemId = params.get("item");
  const itemType: ItemType | "all" = filter === "voice"
    ? "audio"
    : filter;
  useEffect(() => {
    const request = ++listRequest.current;
    let live = true;
    const timer = window.setTimeout(() => {
      if (live && request === listRequest.current) setLoading(true);
      void dataProvider.listItems({
        query: query.trim() || undefined,
        type: itemType,
        limit: PAGE_FETCH_SIZE,
      })
      .then((list) => {
        if (live && request === listRequest.current) {
          setError("");
          setItems(list.slice(0, PAGE_SIZE));
          setHasMore(list.length > PAGE_SIZE);
        }
      })
      .catch((caught) => {
        if (live)
          if (request === listRequest.current) setError(
            dataErrorMessage(
              caught,
              "Vault could not be loaded. Refresh to try again.",
            ),
          );
      })
      .finally(() => {
        if (live && request === listRequest.current) setLoading(false);
      });
    }, 200);
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [revision, query, itemType]);
  useEffect(() => {
    if (!linkedItemId) {
      closedLinkedItem.current = null;
      return;
    }
    if (closedLinkedItem.current === linkedItemId) return;
    let live = true;
    void dataProvider.getItem(linkedItemId)
      .then((item) => {
        if (live) setSelected(item);
      })
      .catch((caught) => {
        if (live) setError(dataErrorMessage(caught, "The linked item could not be loaded."));
      });
    return () => { live = false; };
  }, [linkedItemId, revision]);
  const closeSelected = useCallback(() => {
    if (linkedItemId) {
      closedLinkedItem.current = linkedItemId;
      router.replace(withoutLinkedItem(pathname, params.toString()) as Route, { scroll: false });
    }
    setEditing(false);
    setSelected(null);
  }, [linkedItemId, params, pathname, router]);
  const loadMore = async () => {
    const cursor = items.at(-1);
    if (!cursor || loadingMore || !hasMore) return;
    const request = ++listRequest.current;
    setLoadingMore(true);
    try {
      const list = await dataProvider.listItems({
        query: query.trim() || undefined,
        type: itemType,
        limit: PAGE_FETCH_SIZE,
        beforeUpdatedAt: cursor.updatedAt,
        beforeId: cursor.id,
      });
      if (request !== listRequest.current) return;
      const page = list.slice(0, PAGE_SIZE);
      setItems((current) => {
        const known = new Set(current.map((item) => item.id));
        return [...current, ...page.filter((item) => !known.has(item.id))];
      });
      setHasMore(list.length > PAGE_SIZE);
    } catch (caught) {
      if (request === listRequest.current) {
        setError(dataErrorMessage(caught, "More Vault items could not be loaded."));
      }
    } finally {
      if (request === listRequest.current) setLoadingMore(false);
    }
  };
  const openItem = (item: Item) => {
    void dataProvider.trackEvent({
      eventType: "item_viewed",
      targetType: "item",
      targetId: item.id,
      metadata: {
        sourceType: item.type,
      },
    });
    setEditing(false);
    setSelected(item);
  };
  const beginEdit = () => {
    if (!selected) return;
    setEditTitle(selected.title);
    setEditContent(selected.content);
    setEditSourceUrl(selected.sourceUrl ?? "");
    setError("");
    setEditError("");
    setEditing(true);
  };
  const saveEdit = async () => {
    if (!selected || saving || !editTitle.trim() || !editContent.trim()) return;
    setSaving(true);
    setEditError("");
    try {
      const title = editTitle.trim();
      const content = selected.type === "file" ? editContent : editContent.trim();
      const sourceUrl = editSourceUrl.trim();
      const changes: UpdateItemInput = {
        type: selected.type,
        expectedCurrentVersionId: selected.currentVersionId,
        ...(title !== selected.title ? { title } : {}),
        ...(content !== selected.content ? { content } : {}),
        ...(selected.type === "url" && sourceUrl !== (selected.sourceUrl ?? "")
          ? { sourceUrl }
          : {}),
      };
      if (changes.title === undefined
        && changes.content === undefined
        && changes.sourceUrl === undefined) {
        setEditing(false);
        return;
      }
      const updated = await dataProvider.updateItem(selected.id, changes);
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
      setSelected(updated);
      setEditing(false);
      refresh();
    } catch (caught) {
      setEditError(dataErrorMessage(caught, "The item could not be updated."));
    } finally {
      setSaving(false);
    }
  };
  const deleteSelected = async () => {
    if (!selected || deleting) return;
    if (!window.confirm(`Delete “${selected.title}”?`)) return;
    setDeleting(true);
    setError("");
    try {
      await dataProvider.deleteItem(selected.id);
      setItems((current) => current.filter((item) => item.id !== selected.id));
      closeSelected();
      refresh();
    } catch (caught) {
      setError(dataErrorMessage(caught, "The item could not be deleted."));
    } finally {
      setDeleting(false);
    }
  };
  const visible = items;
  return (
    <section className="page vault-page">
      <header className="page-heading">
        <p className="eyebrow">
          <span className="dot green" />
          PROJECT MEMORY · {items.length} ITEMS LOADED
        </p>
        <h1>Vault</h1>
        <p>Everything Flare remembers about your project.</p>
      </header>
      <div className="vault-toolbar">
        <label className="search-field">
          <Icon name="search" />
          <input
            aria-label="Search vault"
            placeholder="Search notes, voice, files, or context…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setQuery("");
            }}
          />
          <kbd>Esc</kbd>
        </label>
        <div className="view-toggle">
          {["grid", "list"].map((v) => (
            <button
              className={`icon-button ${v === view ? "active" : ""}`}
              key={v}
              aria-label={`${v} view`}
              aria-pressed={v === view}
              onClick={() => setView(v)}
            >
              <Icon name={v === "grid" ? "grid" : "list"} />
            </button>
          ))}
        </div>
      </div>
      <div className="filters">
        {filters.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`filter ${filter === f.id ? "selected" : ""}`}
          >
            {f.label}
          </button>
        ))}
      </div>
      {loading ? (
        <p className="state" role="status">
          Loading your context…
        </p>
      ) : error ? (
        <p role="alert" className="state error-text">
          {error}
        </p>
      ) : !visible.length ? (
        <div className="state">
          <h2>No matching context</h2>
          <p>Try another keyword or filter, or capture something new.</p>
        </div>
      ) : (
        <>
        <div className={`vault-grid ${view === "list" ? "list-view" : ""}`}>
          {visible.map((item) => (
            <article className="card memory-card" key={item.id}>
              <div className="card-meta">
                <span className="badge">{item.sourceLabel ?? item.type}</span>
                {item.type !== "audio" && <Icon name={itemIcon[item.type]} />}
              </div>
              <h2>
                <button
                  className="title-button"
                  onClick={() => openItem(item)}
                >
                  {item.title}
                </button>
              </h2>
              <p className="muted meta">
                {item.author ?? "Team workspace"} ·{" "}
                {new Date(item.createdAt).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                })}
              </p>
              {item.type === "audio" && <p className="voice-provenance">Voice transcript</p>}
              <div className="facts">
                <h3 className="eyebrow muted">{item.extractedFacts.length ? "EXTRACTED FACTS" : "ORIGINAL CONTENT"}</h3>
                {item.extractedFacts.length ? (
                  <ul>
                    {item.extractedFacts.map((fact) => (
                      <li key={fact.id}>{fact.text}</li>
                    ))}
                  </ul>
                ) : (
                  <p>
                    {item.status === "processing"
                      ? "Processing…"
                      : item.content.slice(0, 220)}
                  </p>
                )}
              </div>
              <footer className="card-footer">
                <span>{item.relatedItemIds.length} related items</span>
                  <button
                    className="text-button"
                    onClick={() => openItem(item)}
                  >
                  Open {item.type === "audio" ? "transcript" : "item"}
                  <Icon name="arrow" />
                </button>
              </footer>
            </article>
          ))}
        </div>
        {hasMore && (
          <div className="form-actions">
            <button
              type="button"
              className="button"
              disabled={loadingMore}
              onClick={() => void loadMore()}
            >
              {loadingMore ? "Loading…" : "Load more"}
            </button>
          </div>
        )}
        </>
      )}
      {selected && (
        <Dialog
          title={selected.title}
          onClose={() => { if (!saving) closeSelected(); }}
          className="item-sheet"
        >
          <header className="sheet-header">
            <div>
              <span className="eyebrow muted">
                {selected.sourceLabel ?? selected.type} · {selected.status}
              </span>
              <h2>{selected.title}</h2>
            </div>
            <button
              className="icon-button"
              aria-label="Close item"
              disabled={saving}
              onClick={() => {
                closeSelected();
              }}
            >
              <Icon name="close" />
            </button>
          </header>
          {editing ? (
            <form
              className="item-edit-form"
              onSubmit={(event) => {
                event.preventDefault();
                void saveEdit();
              }}
            >
              <label>
                Title
                <input
                  value={editTitle}
                  maxLength={300}
                  required
                  disabled={saving}
                  onChange={(event) => setEditTitle(event.target.value)}
                />
              </label>
              {selected.type === "url" && (
                <label>
                  URL
                  <input
                    type="url"
                    value={editSourceUrl}
                    maxLength={2048}
                    required
                    disabled={saving}
                    onChange={(event) => setEditSourceUrl(event.target.value)}
                  />
                </label>
              )}
              <label>
                {selected.type === "audio" ? "Transcript" : "Content"}
                <textarea
                  value={editContent}
                  maxLength={200000}
                  rows={12}
                  required
                  disabled={saving}
                  onChange={(event) => setEditContent(event.target.value)}
                />
              </label>
              <p className="muted meta">
                Saving creates version {selected.versionNumber + 1}. Existing Flares keep their original evidence.
              </p>
              {editError && (
                <p className="error-text meta" role="alert">{editError}</p>
              )}
              <div className="form-actions">
                <button
                  type="button"
                  className="button"
                  disabled={saving}
                  onClick={() => setEditing(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="button primary"
                  disabled={saving || !editTitle.trim() || !editContent.trim()}
                >
                  {saving ? "Saving…" : selected.type === "note" ? "Save new version" : "Replace source"}
                </button>
              </div>
            </form>
          ) : (
          <>
          <section>
            <h3>Extracted Facts</h3>
            {selected.extractedFacts.length ? (
              <ul className="detail-facts">
                {selected.extractedFacts.map((fact) => (
                  <li key={fact.id}>{fact.text}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">No extracted facts yet.</p>
            )}
          </section>
          <section>
            <h3>
              {selected.type === "audio" ? "Transcript" : "Original Content"}
            </h3>
            <p className="original-content">{selected.content}</p>
            {selected.sourceUrl && /^https?:\/\//.test(selected.sourceUrl) && (
              <a
                className="text-button"
                href={selected.sourceUrl}
                target="_blank"
                rel="noreferrer"
              >
                Open original URL ↗
              </a>
            )}
            {selected.fileName && (
              <p className="muted">
                {selected.fileName} ·{" "}
                {((selected.fileSize ?? 0) / 1024).toFixed(1)} KB · metadata
                only
              </p>
            )}
          </section>
          <section>
            <h3>Related Items</h3>
            {selected.relatedItemIds.length ? (
              selected.relatedItemIds.map((id) => {
                const item = items.find((i) => i.id === id);
                return item ? (
                  <button
                    key={id}
                    className="related-item"
                    onClick={() => openItem(item)}
                  >
                    <Icon name={itemIcon[item.type]} />
                    {item.title}
                    <Icon name="arrow" />
                  </button>
                ) : (
                  <Link key={id} href={`/vault?item=${id}`}>
                    Open related source
                  </Link>
                );
              })
            ) : (
              <p className="muted">No related items yet.</p>
            )}
          </section>
          <footer className="form-actions item-sheet-actions">
            <button
              type="button"
              className="button primary"
              disabled={session?.workspace.role === "viewer"}
              onClick={beginEdit}
            >
              {selected.type === "note" ? "Edit note" : "Edit source"}
            </button>
            <button
              type="button"
              className="button danger-button"
              disabled={deleting || session?.workspace.role === "viewer"}
              onClick={() => void deleteSelected()}
            >
              {deleting ? "Deleting…" : "Delete item"}
            </button>
          </footer>
          </>
          )}
        </Dialog>
      )}
    </section>
  );
}
