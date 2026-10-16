"use client";
import { useI18n } from "@/i18n/provider";
import Link from "next/link";
import { projectHref } from "@/lib/team-context";
import type { Route } from "next";
import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  dataErrorMessage,
  dataProvider,
  type Item,
  type ItemVersion,
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
  next.delete("version");
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
  const { t, locale, label, message } = useI18n();

  const params = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const session = useSession();
  const { revision, refresh } = useWorkspace();
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Item | null>(null);
  const [sourceVersion, setSourceVersion] = useState<ItemVersion | null>(null);
  const [sourceError, setSourceError] = useState('');
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<VaultFilter>("all");
  const [view, setView] = useState("grid");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const deleteLock = useRef(false);
  const deleteButton = useRef<HTMLButtonElement>(null);
  const cancelDeleteButton = useRef<HTMLButtonElement>(null);
  const wasConfirmingDelete = useRef(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editContent, setEditContent] = useState("");
  const [editSourceUrl, setEditSourceUrl] = useState("");
  const [editError, setEditError] = useState("");
  const listRequest = useRef(0);
  const saveLock = useRef(false);
  const closedLinkedItem = useRef<string | null>(null);
  const closedLinkedVersion = useRef<string | null>(null);
  const linkedItemId = params.get("item");
  const linkedVersionId = params.get('version');
  const selectionRequest = useRef(0);
  useEffect(() => {
    const dirty = editing && selected && (
      editTitle !== selected.title || editContent !== selected.content
      || (selected.type === "url" && editSourceUrl !== (selected.sourceUrl ?? ""))
    );
    if (!saving && !dirty) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [saving, editing, selected, editTitle, editContent, editSourceUrl]);
  useEffect(() => {
    if (confirmingDelete) cancelDeleteButton.current?.focus();
    else if (wasConfirmingDelete.current) deleteButton.current?.focus();
    wasConfirmingDelete.current = confirmingDelete;
  }, [confirmingDelete]);
  const itemType: ItemType | "all" = filter === "voice"
    ? "audio"
    : filter;
  useEffect(() => {
    const request = ++listRequest.current;
    let live = true;
    const timer = window.setTimeout(() => {
      if (live && request === listRequest.current) {
        setLoading(true);
        setLoadingMore(false);
      }
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
      closedLinkedVersion.current = null;
      return;
    }
    if (closedLinkedItem.current === linkedItemId && closedLinkedVersion.current === linkedVersionId) return;
    let live = true;
    const request = ++selectionRequest.current;
    const load = linkedVersionId ? dataProvider.getItemVersion(linkedItemId, linkedVersionId)
      : dataProvider.getItem(linkedItemId).then(item => item ? { item, savedAt: item.updatedAt, isCurrent: true } : null);
    void load.then((snapshot) => {
        if (live && request === selectionRequest.current) {
          if (!snapshot) { setSourceError('This source is unavailable. It may have been removed or your access has changed.'); setSelected(null); setSourceVersion(null); return; }
          setSourceError('');
          setSelected(snapshot.item);
          setSourceVersion(linkedVersionId ? snapshot : null);
          setEditing(false); setConfirmingDelete(false);
        }
      })
      .catch((caught) => {
        if (live && request === selectionRequest.current) { setSourceError(dataErrorMessage(caught, "The linked item could not be loaded.")); setSelected(null); setSourceVersion(null); }
      });
    return () => { live = false; };
  }, [linkedItemId, linkedVersionId, revision]);
  const closeSelected = useCallback(() => {
    ++selectionRequest.current;
    if (linkedItemId) {
      closedLinkedItem.current = linkedItemId;
      closedLinkedVersion.current = linkedVersionId;
      router.replace(withoutLinkedItem(pathname, params.toString()) as Route, { scroll: false });
    }
    setEditing(false);
    setConfirmingDelete(false);
    setSelected(null);
    setSourceVersion(null);
    setSourceError('');
  }, [linkedItemId, linkedVersionId, params, pathname, router]);
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
    ++selectionRequest.current;
    setSourceVersion(null);
    setSourceError('');
    void dataProvider.trackEvent({
      eventType: "item_viewed",
      targetType: "item",
      targetId: item.id,
      metadata: {
        sourceType: item.type,
      },
    });
    setEditing(false);
    setConfirmingDelete(false);
    setSelected(item);
  };
  const beginEdit = () => {
    if (!selected || sourceVersion) return;
    setEditTitle(selected.title);
    setEditContent(selected.content);
    setEditSourceUrl(selected.sourceUrl ?? "");
    setError("");
    setEditError("");
    setEditing(true);
  };
  const saveEdit = async () => {
    if (!selected || sourceVersion || saving || saveLock.current || !editTitle.trim() || !editContent.trim()) return;
    saveLock.current = true;
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
      saveLock.current = false;
      setSaving(false);
    }
  };
  const deleteSelected = async () => {
    if (!selected || sourceVersion || deleting || deleteLock.current || !confirmingDelete) return;
    deleteLock.current = true;
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
      deleteLock.current = false;
      setDeleting(false);
    }
  };
  const visible = items;
  return (
    <section className="page vault-page">
      <header className="page-heading">
        <p className="eyebrow">
          <span className="dot green" />
          {" "}{t("PROJECT MEMORY ·")}{" "}{items.length} {" "}{t("ITEMS LOADED")}</p>
        <h1>Vault</h1>
        <p>{t("Everything Flare remembers about your project.")}</p>
      </header>
      <div className="vault-toolbar">
        <label className="search-field">
          <Icon name="search" />
          <input
            aria-label={t("Search vault")}
            placeholder={t("Search notes, voice, files, or context…")}
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
              aria-label={label(`${v} view`)}
              aria-pressed={v === view}
              onClick={() => setView(v)}
            >
              <Icon name={v === "grid" ? "grid" : "list"} />
            </button>
          ))}
        </div>
      </div>
      {linkedItemId && sourceError && <p role="alert" className="state error-text">{message(sourceError)}</p>}
      <div className="filters">
        {filters.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`filter ${filter === f.id ? "selected" : ""}`}
          >
            {label(f.label)}
          </button>
        ))}
      </div>
      {loading ? (
        <p className="state" role="status">
          {t("Loading your context…")}</p>
      ) : error ? (
        <p role="alert" className="state error-text">
          {message(error)}
        </p>
      ) : !visible.length ? (
        <div className="state">
          <h2>{t("No matching context")}</h2>
          <p>{t("Try another keyword or filter, or capture something new.")}</p>
        </div>
      ) : (
        <>
        <div className={`vault-grid ${view === "list" ? "list-view" : ""}`}>
          {visible.map((item) => (
            <article className="card memory-card" key={item.id}>
              <div className="card-meta">
                <span className="badge">{item.sourceLabel ?? label(item.type)}</span>
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
                {item.author && <>{t("Added by")} {item.author} · </>}
                {new Date(item.createdAt).toLocaleDateString(locale, {
                  month: "short",
                  day: "numeric",
                })}
              </p>
              {item.type === "audio" && <p className="voice-provenance">{t("Voice transcript")}</p>}
              <div className="facts">
                <h3 className="eyebrow muted">{item.extractedFacts.length ? t("EXTRACTED FACTS") : t("ORIGINAL CONTENT")}</h3>
                {item.extractedFacts.length ? (
                  <ul>
                    {item.extractedFacts.map((fact) => (
                      <li key={fact.id}>{fact.text}</li>
                    ))}
                  </ul>
                ) : (
                  <p>
                    {item.status === "processing"
                      ? t("Processing…")
                      : item.content.slice(0, 220)}
                  </p>
                )}
              </div>
              <footer className="card-footer">
                <span>{item.relatedItemIds.length} {" "}{t("related items")}</span>
                  <button
                    className="text-button"
                    onClick={() => openItem(item)}
                  >
                  {t("Open")}{" "}{item.type === "audio" ? t("transcript") : t("item")}
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
              {loadingMore ? t("Loading…") : t("Load more")}
            </button>
          </div>
        )}
        </>
      )}
      {selected && (
        <Dialog
          title={confirmingDelete ? t("deleteItemConfirmation", { title: selected.title }) : selected.title}
          onClose={() => {
            if (saving || deleting) return;
            if (confirmingDelete) setConfirmingDelete(false);
            else closeSelected();
          }}
          className={`item-sheet ${confirmingDelete ? "item-delete-sheet" : ""}`}
        >
          <header className="sheet-header">
            <div>
              <span className="eyebrow muted">
                {selected.sourceLabel ?? label(selected.type)} · {label(selected.status)}
              </span>
              <h2>{confirmingDelete ? t("deleteItemConfirmation", { title: selected.title }) : selected.title}</h2>
              {selected.author && (
                <p className="muted meta" style={{ marginTop: 8 }}>
                  {t("Added by")} {selected.author}
                </p>
              )}
            </div>
            <button
              className="icon-button"
              aria-label={confirmingDelete ? t("Cancel") : t("Close item")}
              disabled={saving || deleting}
              onClick={() => {
                if (confirmingDelete) setConfirmingDelete(false);
                else closeSelected();
              }}
            >
              <Icon name="close" />
            </button>
          </header>
          {sourceVersion && <section className="source-version-notice" aria-label={t('Original source version')}>
            <h3>{t('Original source version')}</h3>
            <p className="muted meta">{t('sourceVersionSavedAt', { version: selected.versionNumber,
              date: new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(sourceVersion.savedAt)) })}</p>
            <p className="muted">{t('sourceVersionNotice')}</p>
          </section>}
          {confirmingDelete ? (
            <div className="item-delete-confirmation">
              {error && <p className="error-text meta" role="alert">{message(error)}</p>}
              <footer className="form-actions item-sheet-actions">
                <button
                  ref={cancelDeleteButton}
                  type="button"
                  className="button"
                  disabled={deleting}
                  onClick={() => setConfirmingDelete(false)}
                >
                  {t("Cancel")}
                </button>
                <button
                  type="button"
                  className="button danger-button"
                  disabled={deleting || session?.workspace.role === "viewer"}
                  onClick={() => void deleteSelected()}
                >
                  {deleting ? t("Deleting…") : t("Delete item")}
                </button>
              </footer>
            </div>
          ) : editing ? (
            <form
              className="item-edit-form"
              onSubmit={(event) => {
                event.preventDefault();
                void saveEdit();
              }}
            >
              <label>
                {t("Title")}{" "}<input
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
                {selected.type === "audio" ? t("Transcript") : t("Content")}
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
                {t("Saving creates version")}{" "}{selected.versionNumber + 1}{t(". Existing Flares keep their original evidence.")}</p>
              {editError && (
                <p className="error-text meta" role="alert">{message(editError)}</p>
              )}
              <div className="form-actions">
                <button
                  type="button"
                  className="button"
                  disabled={saving}
                  onClick={() => setEditing(false)}
                >
                  {t("Cancel")}</button>
                <button
                  type="submit"
                  className="button primary"
                  disabled={saving || !editTitle.trim() || !editContent.trim()}
                >
                  {saving ? t("Saving…") : selected.type === "note" ? t("Save new version") : t("Replace source")}
                </button>
              </div>
            </form>
          ) : (
          <>
          <section>
            <h3>{t("Extracted Facts")}</h3>
            {selected.extractedFacts.length ? (
              <ul className="detail-facts">
                {selected.extractedFacts.map((fact) => (
                  <li key={fact.id}>{fact.text}</li>
                ))}
              </ul>
            ) : (
              <p className="muted">{t("No extracted facts yet.")}</p>
            )}
          </section>
          <section>
            <h3>
              {selected.type === "audio" ? t("Transcript") : t("Original Content")}
            </h3>
            <p className="original-content">{selected.content}</p>
            {selected.sourceUrl && /^https?:\/\//.test(selected.sourceUrl) && (
              <a
                className="text-button"
                href={selected.sourceUrl}
                target="_blank"
                rel="noreferrer"
              >
                {t("Open original URL ↗")}</a>
            )}
            {selected.fileName && (
              <p className="muted">
                {selected.relativePath ?? selected.fileName} ·{" "}
                {t("fileMetadata", { size: new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format((selected.fileSize ?? 0) / 1024) })}</p>
            )}
          </section>
          <section>
            <h3>{t("Related Items")}</h3>
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
                  <Link key={id} href={projectHref(`/vault?item=${encodeURIComponent(id)}`)}>
                    {t("Open related source")}</Link>
                );
              })
            ) : (
              <p className="muted">{t("No related items yet.")}</p>
            )}
          </section>
          {sourceVersion ? <footer className="form-actions item-sheet-actions">
            <Link className="button primary" href={projectHref(`/vault?item=${encodeURIComponent(selected.id)}`)}>{t('Open current version')}</Link>
          </footer> : <footer className="form-actions item-sheet-actions">
            <button
              type="button"
              className="button primary"
              disabled={session?.workspace.role === "viewer"}
              onClick={beginEdit}
            >
              {selected.type === "note" ? t("Edit note") : t("Edit source")}
            </button>
            <button
              ref={deleteButton}
              type="button"
              className="button danger-button"
              disabled={deleting || session?.workspace.role === "viewer"}
              onClick={() => setConfirmingDelete(true)}
            >
              {deleting ? t("Deleting…") : t("Delete item")}
            </button>
          </footer>}
          </>
          )}
        </Dialog>
      )}
    </section>
  );
}
