"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSession } from "@/components/auth-session";
import { Dialog } from "@/components/dialog";
import { Icon } from "@/components/icons";
import { useI18n } from "@/i18n/provider";
import { mailCapability, MailRequestError, parseRecipients, sendMail, type MailCapability, type MailDraft, type MailOutcome } from "./developer-mail-client";
import "./developer-mail.css";

const copy = {
  en: {
    section: "Team email", intro: "Write to users from the Flare email address.", compose: "Compose email",
    title: "New email", from: "From", to: "To", subject: "Subject", body: "Message", close: "Close",
    hint: "Up to 20 addresses, separated by commas, semicolons or new lines. Each receives a separate copy.",
    unavailable: "Sending is not configured yet. Contact the release owner.",
    draft: "Your draft stays here when you close this window.", send: "Send email", sending: "Sending…",
    recipientsError: "Enter 1–20 valid email addresses.", subjectError: "Enter a single-line subject, up to 200 characters.",
    bodyError: "Enter a message, up to 20,000 characters.", failedRequest: "The request was rejected. Your draft is kept; you can try again.",
    accepted: "Accepted by mail provider", failed: "Not sent", unknown: "Could not confirm sending",
    acceptedHint: "Provider acceptance does not confirm inbox delivery.",
    unknownHint: "Check the provider or recipient before sending again. This email may already have been sent.",
    retry: "Retry failed addresses", newMessage: "New email", results: "Send results",
  },
  es: {
    section: "Correo del equipo", intro: "Escribe a los usuarios desde la dirección de Flare.", compose: "Redactar correo",
    title: "Nuevo correo", from: "De", to: "Para", subject: "Asunto", body: "Mensaje", close: "Cerrar",
    hint: "Hasta 20 direcciones separadas por comas, punto y coma o saltos de línea. Cada una recibe una copia independiente.",
    unavailable: "El envío aún no está configurado. Contacta con el responsable del lanzamiento.",
    draft: "El borrador se conserva aquí al cerrar esta ventana.", send: "Enviar correo", sending: "Enviando…",
    recipientsError: "Introduce entre 1 y 20 direcciones válidas.", subjectError: "Introduce un asunto de una línea, de hasta 200 caracteres.",
    bodyError: "Introduce un mensaje de hasta 20.000 caracteres.", failedRequest: "La solicitud fue rechazada. Se conserva el borrador; puedes intentarlo de nuevo.",
    accepted: "Aceptado por el proveedor", failed: "No enviado", unknown: "No se pudo confirmar el envío",
    acceptedHint: "La aceptación del proveedor no confirma la entrega en la bandeja de entrada.",
    unknownHint: "Consulta al proveedor o al destinatario antes de volver a enviar. El correo podría haberse enviado ya.",
    retry: "Reintentar direcciones fallidas", newMessage: "Nuevo correo", results: "Resultados del envío",
  },
};
const emptyDraft: MailDraft = { recipients: "", subject: "", body: "" };

export function DeveloperMail() {
  const session = useSession();
  // A changed account unmounts all private draft/capability state immediately.
  return session ? <MailComposer key={session.user.id} accountId={session.user.id} /> : null;
}

export function MailComposer({ accountId }: { accountId: string }) {
  const { locale } = useI18n();
  const c = copy[locale];
  const [capability, setCapability] = useState<MailCapability | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<MailDraft>(emptyDraft);
  const [pending, setPending] = useState(false);
  const locked = useRef(false);
  const recipientField = useRef<HTMLTextAreaElement>(null);
  const [outcomes, setOutcomes] = useState<MailOutcome[]>([]);
  const [error, setError] = useState<"recipients" | "subject" | "body" | "request" | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    void mailCapability(controller.signal).then(value => { if (live) setCapability(value); }).catch(() => {});
    return () => { live = false; controller.abort(); };
  }, [accountId]);
  useEffect(() => { if (open) recipientField.current?.focus(); }, [open]);

  function close() { if (!locked.current) setOpen(false); }
  function update(field: keyof MailDraft, value: string) {
    setDraft(current => ({ ...current, [field]: value })); setError(null);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (locked.current || !capability?.ready || outcomes.some(value => value.status === "unknown")) return;
    if (outcomes.length && outcomes.every(value => value.status === "accepted")) return;
    let recipients: string[];
    try { recipients = outcomes.length ? outcomes.filter(value => value.status === "failed").map(value => value.recipient) : parseRecipients(draft.recipients); }
    catch { setError("recipients"); return; }
    if (!draft.subject.trim() || draft.subject.length > 200 || /[\x00-\x1f\x7f]/.test(draft.subject)) { setError("subject"); return; }
    if (!draft.body.trim() || draft.body.length > 20_000 || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(draft.body)) { setError("body"); return; }
    locked.current = true; setPending(true); setError(null);
    try {
      const result = await sendMail(recipients, draft);
      setOutcomes(previous => previous.length ? previous.map(value => result.find(next => next.recipient === value.recipient) ?? value) : result);
    } catch (failure) {
      if (failure instanceof MailRequestError && !failure.uncertain) setError("request");
      else setOutcomes(previous => {
        const result = recipients.map(recipient => ({ recipient, status: "unknown" as const }));
        return previous.length ? previous.map(value => result.find(next => next.recipient === value.recipient) ?? value) : result;
      });
    } finally { locked.current = false; setPending(false); }
  }
  if (!capability?.allowed) return null;
  const hasUnknown = outcomes.some(value => value.status === "unknown");
  const canRetry = outcomes.some(value => value.status === "failed") && !hasUnknown;
  const readOnly = pending || outcomes.length > 0;
  const fieldError = error === "recipients" ? c.recipientsError : error === "subject" ? c.subjectError : error === "body" ? c.bodyError : error === "request" ? c.failedRequest : "";
  return (
    <section className="card settings-section developer-mail-section">
      <header><h2><Icon name="note" />{c.section}</h2><p className="muted meta">{c.intro}</p></header>
      <div className="setting-row">
        <div className="setting-row-copy"><h3>{capability.sender ?? c.section}</h3><p className="muted meta">{capability.ready ? c.intro : c.unavailable}</p></div>
        <button type="button" className="button" onClick={() => setOpen(true)}>{c.compose}</button>
      </div>
      {open && <Dialog title={c.title} onClose={close} className="developer-mail-sheet">
        <header className="sheet-header"><div><h2>{c.title}</h2><p className="muted meta">{c.draft}</p></div>
          <button type="button" className="icon-button" aria-label={c.close} disabled={pending} onClick={close}><Icon name="close" /></button>
        </header>
        <form onSubmit={submit} noValidate aria-busy={pending}>
          <div className="developer-mail-from"><span className="muted">{c.from}</span><strong>{capability.sender ?? "—"}</strong></div>
          <label htmlFor="mail-recipients">{c.to}<textarea id="mail-recipients" ref={recipientField} rows={2} value={draft.recipients} readOnly={readOnly} maxLength={5200}
            onChange={event => update("recipients", event.target.value)} aria-invalid={error === "recipients"} aria-describedby={`mail-recipients-hint${error === "recipients" ? " mail-error" : ""}`} /></label>
          <p id="mail-recipients-hint" className="muted meta">{c.hint}</p>
          <label htmlFor="mail-subject">{c.subject}<input id="mail-subject" value={draft.subject} readOnly={readOnly} maxLength={200}
            onChange={event => update("subject", event.target.value)} aria-invalid={error === "subject"} aria-describedby={error === "subject" ? "mail-error" : undefined} /></label>
          <label htmlFor="mail-body">{c.body}<textarea id="mail-body" rows={9} value={draft.body} readOnly={readOnly} maxLength={20_000}
            onChange={event => update("body", event.target.value)} aria-invalid={error === "body"} aria-describedby={error === "body" ? "mail-error" : undefined} /></label>
          {!capability.ready && <p role="status" className="developer-mail-notice">{c.unavailable}</p>}
          {fieldError && <p id="mail-error" role="alert" className="developer-mail-notice">{fieldError}</p>}
          {outcomes.length > 0 && <div className="developer-mail-results" role="status" aria-label={c.results}>
            <ul>{outcomes.map(value => <li key={value.recipient}><span>{value.recipient}</span><strong>{c[value.status]}</strong></li>)}</ul>
            <p className="muted meta">{hasUnknown ? c.unknownHint : c.acceptedHint}</p>
          </div>}
          <footer className="developer-mail-actions">
            {outcomes.length > 0 && <button type="button" className="button" disabled={pending} onClick={() => { setDraft(emptyDraft); setOutcomes([]); setError(null); }}>{c.newMessage}</button>}
            <button type="button" className="button" disabled={pending} onClick={close}>{c.close}</button>
            {(!outcomes.length || canRetry) && <button type="submit" className="button primary" disabled={pending || !capability.ready}>{pending ? c.sending : canRetry ? c.retry : c.send}</button>}
          </footer>
        </form>
      </Dialog>}
    </section>
  );
}
