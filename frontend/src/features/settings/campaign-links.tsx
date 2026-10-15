"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useSession } from "@/components/auth-session";
import { Icon } from "@/components/icons";
import { Select } from "@/components/select";
import { useI18n } from "@/i18n/provider";
import {
  archiveCampaignLink,
  CampaignLinkError,
  CampaignLinkDraftError,
  createCampaignLink,
  listCampaignLinks,
  type CampaignLink,
  type CampaignLinkDraft,
} from "./campaign-links-client";
import "./campaign-links.css";

const copy = {
  en: {
    title: "Campaign links",
    subtitle: "Create trackable Flare links and compare their aggregate recorded opens.",
    label: "Link label",
    labelPlaceholder: "October founder post",
    destination: "Destination",
    source: "Source",
    sourcePlaceholder: "x",
    medium: "Medium",
    mediumPlaceholder: "organic_social",
    campaign: "Campaign",
    campaignPlaceholder: "launch_2026_10",
    content: "Content (optional)",
    contentPlaceholder: "founder_video",
    utmNote: "UTM values appear in the destination URL. Do not put names, email addresses, or confidential information in these fields.",
    create: "Create link",
    creating: "Creating…",
    created: "Campaign link created.",
    activeLinks: "Created links",
    loading: "Loading campaign links…",
    empty: "No campaign links yet.",
    redirects: "Recorded link opens",
    countNote: "This is an aggregate count with no visitor identifiers. Repeat opens, automated previews, and bots can increase it; temporary service contention can miss opens. It is not a count of unique people.",
    archiveNote: "Archiving stops future opens from being counted. The existing link will keep redirecting.",
    copy: "Copy",
    copied: "Link copied.",
    copyFailed: "Could not copy the link. Select and copy it manually.",
    archive: "Archive",
    archiving: "Archiving…",
    archived: "Archived",
    archivedHelp: "Archived links still redirect, but no longer increase this count.",
    archivedMessage: "Campaign link archived.",
    invalid: "Use a label up to 80 characters and lowercase letters, numbers, dots, dashes or underscores for UTM fields.",
    limit: "You can keep up to 25 active campaign links. Archive one before creating another.",
    failed: "Campaign links could not be updated. Please retry.",
  },
  es: {
    title: "Enlaces de campaña",
    subtitle: "Crea enlaces medibles de Flare y compara sus aperturas registradas agregadas.",
    label: "Nombre del enlace",
    labelPlaceholder: "Publicación de fundadores de octubre",
    destination: "Destino",
    source: "Fuente",
    sourcePlaceholder: "x",
    medium: "Medio",
    mediumPlaceholder: "organic_social",
    campaign: "Campaña",
    campaignPlaceholder: "launch_2026_10",
    content: "Contenido (opcional)",
    contentPlaceholder: "founder_video",
    utmNote: "Los valores UTM aparecen en la URL de destino. No incluyas nombres, correos electrónicos ni información confidencial en estos campos.",
    create: "Crear enlace",
    creating: "Creando…",
    created: "Enlace de campaña creado.",
    activeLinks: "Enlaces creados",
    loading: "Cargando enlaces de campaña…",
    empty: "Aún no hay enlaces de campaña.",
    redirects: "Aperturas registradas",
    countNote: "Este es un conteo agregado sin identificadores de visitantes. Las aperturas repetidas, las vistas previas automáticas y los bots pueden aumentarlo; una sobrecarga temporal del servicio puede omitir aperturas. No representa personas únicas.",
    archiveNote: "Al archivar, las aperturas futuras dejan de contarse. El enlace existente seguirá redirigiendo.",
    copy: "Copiar",
    copied: "Enlace copiado.",
    copyFailed: "No se pudo copiar el enlace. Selecciónalo y cópialo manualmente.",
    archive: "Archivar",
    archiving: "Archivando…",
    archived: "Archivado",
    archivedHelp: "Los enlaces archivados siguen redirigiendo, pero ya no aumentan este conteo.",
    archivedMessage: "Enlace de campaña archivado.",
    invalid: "Usa un nombre de hasta 80 caracteres y letras minúsculas, números, puntos, guiones o guiones bajos en los campos UTM.",
    limit: "Puedes mantener hasta 25 enlaces de campaña activos. Archiva uno antes de crear otro.",
    failed: "No se pudieron actualizar los enlaces de campaña. Inténtalo de nuevo.",
  },
};

const emptyDraft: CampaignLinkDraft = {
  label: "",
  destinationPath: "/",
  utmSource: "",
  utmMedium: "",
  utmCampaign: "",
  utmContent: "",
};

export function visibleCampaignLinks(values: CampaignLink[]): CampaignLink[] {
  return [...values]
    .sort((left, right) => {
      const archiveOrder = Number(Boolean(left.archivedAt)) - Number(Boolean(right.archivedAt));
      if (archiveOrder !== 0) return archiveOrder;
      return Date.parse(right.createdAt) - Date.parse(left.createdAt);
    })
    .slice(0, 100);
}

export function CampaignLinks() {
  const session = useSession();
  return session?.workspace.role === "owner" ? <CampaignLinksPanel /> : null;
}

export function CampaignLinksPanel() {
  const { locale } = useI18n();
  const c = copy[locale];
  const [links, setLinks] = useState<CampaignLink[]>([]);
  const [draft, setDraft] = useState<CampaignLinkDraft>(emptyDraft);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [archiving, setArchiving] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void listCampaignLinks(controller.signal)
      .then(values => setLinks(visibleCampaignLinks(values)))
      .catch(() => {
        if (!controller.signal.aborted) {
          setError(true);
          setStatus(c.failed);
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [c.failed]);

  function update(field: keyof CampaignLinkDraft, value: string) {
    setDraft(current => ({ ...current, [field]: value }));
    setStatus("");
    setError(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (creating) return;
    setCreating(true);
    setStatus("");
    setError(false);
    try {
      const created = await createCampaignLink(draft);
      setLinks(current => visibleCampaignLinks([created, ...current.filter(link => link.id !== created.id)]));
      setDraft(current => ({ ...emptyDraft, destinationPath: current.destinationPath, utmSource: current.utmSource, utmMedium: current.utmMedium }));
      setStatus(c.created);
    } catch (cause) {
      setError(true);
      setStatus(cause instanceof CampaignLinkDraftError
        ? c.invalid
        : cause instanceof CampaignLinkError && cause.status === 409
          ? c.limit
          : c.failed);
    } finally {
      setCreating(false);
    }
  }

  async function copyLink(link: CampaignLink) {
    try {
      await navigator.clipboard.writeText(link.shortUrl);
      setError(false);
      setStatus(c.copied);
    } catch {
      setError(true);
      setStatus(c.copyFailed);
    }
  }

  async function archive(link: CampaignLink) {
    if (archiving) return;
    setArchiving(link.id);
    setStatus("");
    setError(false);
    try {
      await archiveCampaignLink(link.id);
      setLinks(current => visibleCampaignLinks(current.map(value => value.id === link.id
        ? { ...value, archivedAt: new Date().toISOString() }
        : value)));
      setStatus(c.archivedMessage);
    } catch {
      setError(true);
      setStatus(c.failed);
    } finally {
      setArchiving(null);
    }
  }

  return (
    <section className="card settings-section campaign-links-section">
      <header>
        <h2><Icon name="url" />{c.title}</h2>
        <p className="muted meta">{c.subtitle}</p>
      </header>
      <form className="campaign-link-form" onSubmit={submit} noValidate>
        <label>{c.label}
          <input value={draft.label} maxLength={80} placeholder={c.labelPlaceholder}
            onChange={event => update("label", event.target.value)} />
        </label>
        <label>{c.destination}
          <Select value={draft.destinationPath} name="destinationPath" aria-label={c.destination}
            onValueChange={value => update("destinationPath", value)}
            options={[
              { value: "/", label: "flare4u.tech/" },
              { value: "/register", label: "flare4u.tech/register" },
              { value: "/login", label: "flare4u.tech/login" },
            ]} />
        </label>
        <label>{c.source}
          <input value={draft.utmSource} maxLength={80} placeholder={c.sourcePlaceholder}
            onChange={event => update("utmSource", event.target.value)} />
        </label>
        <label>{c.medium}
          <input value={draft.utmMedium} maxLength={80} placeholder={c.mediumPlaceholder}
            onChange={event => update("utmMedium", event.target.value)} />
        </label>
        <label>{c.campaign}
          <input value={draft.utmCampaign} maxLength={80} placeholder={c.campaignPlaceholder}
            onChange={event => update("utmCampaign", event.target.value)} />
        </label>
        <label>{c.content}
          <input value={draft.utmContent} maxLength={80} placeholder={c.contentPlaceholder}
            onChange={event => update("utmContent", event.target.value)} />
        </label>
        <p className="campaign-link-form-note muted meta">{c.utmNote}</p>
        <div className="campaign-link-submit">
          <button type="submit" className="button primary" disabled={creating}>
            {creating ? c.creating : c.create}
          </button>
        </div>
      </form>
      {status && <p className={`campaign-link-status ${error ? "is-error" : ""}`} role={error ? "alert" : "status"}>{status}</p>}
      <div className="campaign-links-heading">
        <h3>{c.activeLinks}</h3>
        <p className="muted meta">{c.countNote}</p>
        <p className="muted meta">{c.archiveNote}</p>
      </div>
      {loading ? <p className="muted" role="status">{c.loading}</p> : links.length === 0 ? (
        <p className="muted campaign-links-empty">{c.empty}</p>
      ) : (
        <ul className="campaign-links-list" aria-label={c.activeLinks}>
          {links.map(link => <li key={link.id} className={link.archivedAt ? "is-archived" : ""}>
            <div className="campaign-link-main">
              <div className="campaign-link-title">
                <strong>{link.label}</strong>
                {link.archivedAt && <span className="badge">{c.archived}</span>}
              </div>
              <code>{link.shortUrl}</code>
              <p className="muted meta">
                {link.destinationPath} · {link.utmSource} / {link.utmMedium} / {link.utmCampaign}
                {link.utmContent ? ` / ${link.utmContent}` : ""}
              </p>
              {link.archivedAt && <p className="muted meta">{c.archivedHelp}</p>}
            </div>
            <div className="campaign-link-metric">
              <strong>{link.clickCount.toLocaleString(locale)}</strong>
              <span>{c.redirects}</span>
            </div>
            <div className="campaign-link-actions">
              <button type="button" className="button" onClick={() => void copyLink(link)}>{c.copy}</button>
              {!link.archivedAt && <button type="button" className="button" disabled={archiving === link.id}
                onClick={() => void archive(link)}>{archiving === link.id ? c.archiving : c.archive}</button>}
            </div>
          </li>)}
        </ul>
      )}
    </section>
  );
}
