"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { dataErrorMessage, dataProvider, type Item } from "@/lib/data";
import { useWorkspace } from "@/components/workspace-context";
import { Icon, itemIcon } from "@/components/icons";
import { Dialog } from "@/components/dialog";
const category = (item: Item) =>
  item.category ?? (item.type === "audio" ? "voice" : "note");
const filters = [
  { id: "all", label: "All" },
  { id: "note", label: "Notes" },
  { id: "voice", label: "Voice" },
  { id: "file", label: "Files" },
];
export function VaultPage() {
  const params = useSearchParams();
  const { revision, refresh } = useWorkspace();
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Item | null>(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [view, setView] = useState("grid");
  const [sort, setSort] = useState("latest");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    let live = true;
    const itemId = params.get("item");
    void Promise.all([
      dataProvider.listItems(),
      itemId ? dataProvider.getItem(itemId) : Promise.resolve(null),
    ])
      .then(([list, linkedItem]) => {
        if (live) {
          setError("");
          setItems(list);
          setSelected(linkedItem);
        }
      })
      .catch((caught) => {
        if (live)
          setError(
            dataErrorMessage(
              caught,
              "Vault could not be loaded. Refresh to try again.",
            ),
          );
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [revision, params]);
  const matches = (i: Item, id: string) =>
    id === "all" || category(i) === id || i.type === id;
  const deleteSelected = async () => {
    if (!selected || deleting) return;
    if (!window.confirm(`Delete “${selected.title}”?`)) return;
    setDeleting(true);
    setError("");
    try {
      await dataProvider.deleteItem(selected.id);
      setItems((current) => current.filter((item) => item.id !== selected.id));
      setSelected(null);
      refresh();
    } catch (caught) {
      setError(dataErrorMessage(caught, "The item could not be deleted."));
    } finally {
      setDeleting(false);
    }
  };
  const visible = items
    .filter(
      (i) =>
        matches(i, filter) &&
        `${i.title} ${i.content} ${i.sourceLabel ?? ""}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort((a, b) =>
      sort === "title"
        ? a.title.localeCompare(b.title)
        : b.createdAt.localeCompare(a.createdAt),
    );
  return (
    <section className="page vault-page">
      <header className="page-heading">
        <p className="eyebrow">
          <span className="dot green" />
          PROJECT MEMORY · {items.length} ITEMS REMEMBERED
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
        <select
          className="button"
          aria-label="Sort vault"
          value={sort}
          onChange={(e) => setSort(e.target.value)}
        >
          <option value="latest">Latest first</option>
          <option value="title">Title A–Z</option>
        </select>
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
            <span>{items.filter((i) => matches(i, f.id)).length}</span>
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
        <div className={`vault-grid ${view === "list" ? "list-view" : ""}`}>
          {visible.map((item) => (
            <article className="card memory-card" key={item.id}>
              <div className="card-meta">
                <span className="badge">{item.sourceLabel ?? item.type}</span>
                <Icon name={itemIcon[item.type]} />
              </div>
              <h2>
                <button
                  className="title-button"
                  onClick={() => setSelected(item)}
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
              {item.type === "audio" && (
                <button
                  className="audio-preview"
                  onClick={() => setSelected(item)}
                  aria-label={`Read transcript: ${item.title}`}
                >
                  <Icon name="audio" />
                  <span className="waveform">
                    {Array.from({ length: 16 }, (_, i) => (
                      <i
                        key={i}
                        style={{ height: `${6 + ((i * 7) % 20)}px` }}
                      />
                    ))}
                  </span>
                  <span>Transcript</span>
                </button>
              )}
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
                      ? "Processing… Demo transcript available in item detail."
                      : item.content.slice(0, 220)}
                  </p>
                )}
              </div>
              <footer className="card-footer">
                <span>{item.relatedItemIds.length} related items</span>
                <button
                  className="text-button"
                  onClick={() => setSelected(item)}
                >
                  Open {item.type === "audio" ? "transcript" : "item"}
                  <Icon name="arrow" />
                </button>
              </footer>
            </article>
          ))}
        </div>
      )}
      {selected && (
        <Dialog
          title={selected.title}
          onClose={() => setSelected(null)}
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
              onClick={() => setSelected(null)}
            >
              <Icon name="close" />
            </button>
          </header>
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
                    onClick={() => setSelected(item)}
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
          <footer className="form-actions">
            <button
              type="button"
              className="button"
              disabled={deleting}
              onClick={() => void deleteSelected()}
            >
              {deleting ? "Deleting…" : "Delete item"}
            </button>
          </footer>
        </Dialog>
      )}
    </section>
  );
}
