"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { dataProvider, type Item } from "@/lib/data";
import { importRequest } from "@/lib/data/import-request";
import { useWorkspace } from "@/components/workspace-context";
import { useSession } from "@/components/auth-session";
import { Select } from "@/components/select";
import { Dialog } from "@/components/dialog";
import { Icon } from "@/components/icons";
import { useI18n } from "@/i18n/provider";
import { projectHref, switchProject } from "@/lib/team-context";
import { teamRequest, type ProjectsResponse, type Member, type Invitation } from "./api";

type Confirmation = { kind?:"transfer"|"rename"; title:string; description:string; run:()=>Promise<unknown> };
export function TeamPage() {
  const { revision, openCapture } = useWorkspace();
  const session = useSession(); const { locale } = useI18n(); const es = locale === "es";
  const copy = (en:string, spanish:string) => es ? spanish : en;
  const wid = session?.workspace.id;
  const [data,setData] = useState<ProjectsResponse | null>(null);
  const [members,setMembers] = useState<Member[]>([]);
  const [invitations,setInvitations] = useState<Invitation[]>([]);
  const [notes,setNotes] = useState<Item[]>([]);
  const [notesError,setNotesError] = useState("");
  const [usage,setUsage] = useState<{contentBytes:number;documents:number;limits:{contentBytes:number;documents:number}}|null>(null);
  const [tab,setTab] = useState("notes");
  const [error,setError] = useState(""); const [notice,setNotice] = useState("");
  const [loading,setLoading] = useState(true); const [busy,setBusy] = useState(false);
  const lock=useRef(false);
  const [invite,setInvite] = useState(false); const [email,setEmail] = useState(""); const [inviteRole,setInviteRole] = useState("editor");
  const [acknowledged,setAcknowledged] = useState(false);
  const [projectName,setProjectName] = useState("");
  const [confirmation,setConfirmation] = useState<Confirmation | null>(null);
  const project=data?.projects.find(p=>p.id===wid);
  const owner=project?.role==="owner"; const writable=project?.writable && project.role!=="viewer";
  const date=(value:string)=>new Date(value).toLocaleString(locale,{dateStyle:"medium",timeStyle:"short"});
  const invitationLabel=(value:string)=>({pending:copy("Awaiting acceptance","Pendiente de aceptación"),accepted:copy("Accepted","Aceptada"),canceled:copy("Canceled","Cancelada"),expired:copy("Expired","Caducada")}[value]??value);

  async function reload(signal?:AbortSignal) {
    const result=await teamRequest<ProjectsResponse>("/projects",undefined,undefined,signal); if(signal?.aborted)return; setData(result);
    const p=result.projects.find(p=>p.id===wid);
    if(p?.kind==="team") {
      const [people,capacity]=await Promise.all([teamRequest<Member[]>(`/projects/${wid}/members`,undefined,undefined,signal),
        teamRequest<NonNullable<typeof usage>>(`/projects/${wid}/usage`,undefined,undefined,signal)]);
      if(signal?.aborted)return;
      setMembers(people);setUsage(capacity);
      if(p.role==="owner") {
        const pending=await teamRequest<Invitation[]>(`/projects/${wid}/invitations`,undefined,undefined,signal);
        if(signal?.aborted)return;
        setInvitations(pending);
      } else setInvitations([]);
      try {
        const shared=await importRequest(()=>dataProvider.listItems({limit:5}),signal,12_000);
        if(signal?.aborted)return;
        setNotes(shared);setNotesError("");
      } catch(cause) {
        if(signal?.aborted)return;
        setNotesError(cause instanceof Error ? cause.message : copy("Shared notes could not load. Try again.","No se pudieron cargar las notas compartidas. Reintenta."));
      }
    }
  }
  useEffect(()=>{
    const controller=new AbortController();
    void Promise.resolve().then(()=>reload(controller.signal)).catch(cause=>{if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Team could not load.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
    // One component instance belongs to one validated project.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[wid,revision]);
  useEffect(()=>{
    if(!invite)return;
    const guard=(event:BeforeUnloadEvent)=>{if(email){event.preventDefault();event.returnValue="";}};
    window.addEventListener("beforeunload",guard);return()=>window.removeEventListener("beforeunload",guard);
  },[invite,email]);

  async function run(action:()=>Promise<unknown>,done:string,onSuccess?:()=>void) {
    if(lock.current)return;lock.current=true;setBusy(true);setError("");setNotice("");
    try{await action();onSuccess?.();setNotice(done);await reload();window.dispatchEvent(new Event("flare:team-refresh"));}
    catch(cause){setError(cause instanceof Error?cause.message:copy("This action could not complete.","No se pudo completar esta acción."));}
    finally{lock.current=false;setBusy(false);}
  }
  return <section className="page team-page">
    <header className="page-heading"><h1>{project?.kind==="team"?project.name:"Team"}</h1><p>{copy("Everyone’s notes in one place. Shared Flares from your project’s context.","Las notas de todos en un lugar. Flares compartidos a partir del contexto del proyecto.")}</p></header>
    {error&&!invite&&<p role="alert" className="team-feedback team-error">{error}</p>}
    {notice&&<p role="status" className="team-feedback">{notice}</p>}
    {loading?<p role="status">{copy("Loading your team…","Cargando tu equipo…")}</p>:!data?<div className="card team-empty"><h2>{copy("Team is not enabled yet","Team aún no está habilitado")}</h2><p>{copy("Your existing project is available. Team needs its billing and email configuration before launch.","Tu proyecto sigue disponible. Team requiere configurar pagos y correo antes de activarlo.")}</p><button className="button" onClick={()=>void run(()=>reload(),"")}>{copy("Try again","Reintentar")}</button></div>
      :project?.kind!=="team"?<div className="card team-empty"><Icon name="team"/><h2>{copy("A shared project for your team","Un proyecto compartido para tu equipo")}</h2><p>{copy("Save notes together and get Flares from the combined context. Invite colleagues by email; personal notes stay in personal projects.","Guarda notas con tu equipo y recibe Flares del contexto compartido. Invita por correo; las notas personales siguen en los proyectos personales.")}</p>
        <p className="muted">{copy(`Your Team license includes up to ${data.capability.limits.members} members. Only the owner needs the subscription.`,`Tu licencia Team incluye hasta ${data.capability.limits.members} miembros. Solo el propietario necesita la suscripción.`)}</p>
        {data.capability.requiresVerification&&<button className="button" disabled={busy} onClick={()=>void run(()=>teamRequest("/verify-email",{}),copy("Verification email sent. Open its link, then refresh this page.","Correo de verificación enviado. Abre el enlace y actualiza esta página."))}>{copy("Verify my email","Verificar mi correo")}</button>}
        <div className="team-actions"><a className="button" href="/settings#subscription">{copy("View subscription","Ver suscripción")}</a>
          <button className="button primary" onClick={()=>window.dispatchEvent(new Event("flare:create-project"))}>{copy("Create team project","Crear proyecto de equipo")}</button></div>
      </div>:<>
        {!project.writable&&<div className="team-feedback" role="status">{copy("This project is read-only. Your materials are preserved; the license owner can renew Team to continue adding content.","Este proyecto es de solo lectura. Tus materiales se conservan; el propietario de la licencia puede renovar Team para añadir contenido.")}</div>}
        {usage&&<div className="team-capacity"><span>{copy("Saved sources","Fuentes guardadas")} <strong>{usage.documents}/{usage.limits.documents}</strong></span><span>{copy("Storage","Almacenamiento")} <strong>{(usage.contentBytes/1048576).toFixed(1)}/{Math.round(usage.limits.contentBytes/1048576)} MiB</strong></span><progress value={usage.contentBytes} max={usage.limits.contentBytes} aria-label={copy("Project storage used","Almacenamiento utilizado")}/><small>{copy("Saved versions count toward storage.","Las versiones guardadas cuentan para el almacenamiento.")}</small></div>}
        <div className="team-toolbar"><div className="team-tabs" role="group" aria-label={copy("Team views","Vistas del equipo")}>
          <button className={tab==="notes"?"button active":"button"} aria-pressed={tab==="notes"} onClick={()=>setTab("notes")}>{copy("Shared notes","Notas compartidas")}</button>
          <button className={tab==="members"?"button active":"button"} aria-pressed={tab==="members"} onClick={()=>setTab("members")}>{copy("Members","Miembros")} <span className="muted">{members.length}/{data.capability.limits.members}</span></button></div>
          {tab==="notes"?<button className="button primary" disabled={!writable||busy} onClick={()=>openCapture()}><Icon name="plus"/>{copy("Add a note","Añadir nota")}</button>
            :owner&&<button className="button primary" disabled={!project.writable||busy} onClick={()=>{setEmail("");setAcknowledged(false);setError("");setInvite(true);}}><Icon name="plus"/>{copy("Invite member","Invitar miembro")}</button>}
        </div>
        {tab==="notes"?<div className="team-context">
          <section className="card team-shared-notes" aria-labelledby="team-notes-heading">
            <div className="team-context-heading"><h2 id="team-notes-heading">{copy("Shared Vault","Vault compartido")}</h2><Link className="text-button" href={projectHref("/vault")}>{copy("Open Vault","Abrir Vault")} <Icon name="arrow"/></Link></div>
            <p className="muted">{copy("Notes and imports saved in this project are visible to its members. Your personal Vault stays separate.","Las notas e importaciones del proyecto son visibles para sus miembros. Tu Vault personal permanece separado.")}</p>
            {notesError?<div className="team-feedback" role="alert"><p>{notesError}</p><button className="button" disabled={busy} onClick={()=>void run(()=>reload(),"")}>{copy("Try again","Reintentar")}</button></div>
              :notes.length===0?<div className="team-note-empty"><h3>{copy("Your first shared note","Tu primera nota compartida")}</h3><p className="muted">{copy("Add an idea, a decision or a customer conversation. Flare will use the shared context in the next scheduled analysis.","Añade una idea, una decisión o una conversación con un cliente. Flare usará el contexto compartido en el próximo análisis programado.")}</p></div>
              :<ul className="team-note-list">{notes.map(note=><li key={note.id}><Link href={projectHref(`/vault?item=${encodeURIComponent(note.id)}`)}><strong>{note.title}</strong><span className="muted">{note.author&&<span>{copy("Added by","Añadida por")} {note.author} · </span>}<time dateTime={note.createdAt}>{date(note.createdAt)}</time></span></Link></li>)}</ul>}
            <Link className="button" href={projectHref("/sources")}>{copy("Add from Sources","Añadir desde Fuentes")}</Link>
          </section>
          <section className="card team-shared-flares" aria-labelledby="team-flares-heading"><h2 id="team-flares-heading">{copy("Shared Flares","Flares compartidos")}</h2><p className="muted">{copy("Flare analyzes the saved context from all members together. Everyone sees the same insights and the notes behind them.","Flare analiza conjuntamente el contexto de todos los miembros. Todos ven los mismos insights y sus notas de origen.")}</p>
            <p className="muted meta">{copy("One analysis schedule for this project. Adding a note does not start a separate analysis.","Un horario de análisis para este proyecto. Añadir una nota no inicia otro análisis.")}</p>
            <div className="team-context-links"><Link className="button" href={projectHref("/insights")}>{copy("Open Flares","Abrir Flares")}</Link><Link className="text-button" href={projectHref("/settings")}>{copy("Analysis schedule","Horario de análisis")}</Link></div>
          </section>
        </div>:<div className="card team-members"><h2>{copy("Project members","Miembros del proyecto")}</h2>
          {members.map(member=><div className="team-member" key={member.id}><div className="team-avatar" aria-hidden="true">{member.name.slice(0,1).toUpperCase()}</div><div className="team-member-copy"><strong>{member.name}{member.id===session?.user.id?copy(" · You"," · Tú"):""}</strong>{member.email&&<small>{member.email}</small>}</div>
            {owner&&member.role!=="owner"?<><Select value={member.role} onValueChange={role=>void run(()=>teamRequest(`/projects/${wid}/members/${encodeURIComponent(member.id)}`,{action:"role",role}),copy("Role updated.","Rol actualizado."))} disabled={busy} variant="compact" aria-label={copy(`Role for ${member.name}`,`Rol de ${member.name}`)} options={[{value:"editor",label:copy("Editor","Editor")},{value:"viewer",label:copy("Viewer","Lector")}]}/>
              <button className="button ghost" disabled={busy} onClick={()=>setConfirmation({title:copy("Remove this member?","¿Eliminar este miembro?"),description:copy(`${member.name} will lose access to this project. Shared materials will stay.`,`${member.name} perderá acceso al proyecto. Los materiales compartidos se conservarán.`),run:()=>teamRequest(`/projects/${wid}/members/${encodeURIComponent(member.id)}`,{action:"remove"})})}>{copy("Remove","Eliminar")}</button></>
              :<span className="team-role">{member.role==="owner"?copy("Owner","Propietario"):member.role==="editor"?copy("Editor","Editor"):copy("Viewer","Lector")}</span>}</div>)}
          {owner&&<><h3>{copy("Invitations","Invitaciones")}</h3><p className="muted">{copy("Pending invitations reserve a seat and expire after seven days.","Las invitaciones pendientes reservan una plaza y caducan después de siete días.")}</p>
            {invitations.length===0?<p className="team-empty-copy">{copy("No invitations yet.","Aún no hay invitaciones.")}</p>:invitations.map(inv=><div className="team-member" key={inv.id}><div className="team-member-copy"><strong>{inv.email}</strong><small>{invitationLabel(inv.status)} · {inv.role==="editor"?copy("Editor","Editor"):copy("Viewer","Lector")} · {date(inv.expiresAt)}</small></div>
              {inv.status==="pending"&&<><button className="button ghost" disabled={busy||!project.writable} onClick={()=>{setEmail(inv.email);setInviteRole(inv.role);setAcknowledged(false);setError("");setInvite(true);}}>{copy("Send again","Reenviar")}</button>
                <button className="button ghost" disabled={busy} onClick={()=>void run(()=>teamRequest(`/projects/${wid}/invitations/${inv.id}`,undefined,"DELETE"),copy("Invitation canceled.","Invitación cancelada."))}>{copy("Cancel","Cancelar")}</button></>}</div>)}</>}
          <div className="team-members-footer">{owner&&<button className="button" disabled={busy} onClick={()=>{setProjectName(project.name);setConfirmation({kind:"rename",title:copy("Rename project","Cambiar nombre del proyecto"),description:copy("Your members, materials and subscription stay with this project.","Los miembros, materiales y suscripción permanecen en este proyecto."),run:async()=>{}});}}>{copy("Rename project","Cambiar nombre del proyecto")}</button>}{owner?<button className="button" disabled={busy||members.length<2} onClick={()=>setConfirmation({kind:"transfer",title:copy("Transfer project ownership","Transferir propiedad del proyecto"),description:copy("Choose an existing member below. Billing remains with the original license owner.","Elige un miembro. La facturación permanece con el propietario original de la licencia."),run:async()=>{}})}>{copy("Transfer ownership","Transferir propiedad")}</button>
            :<button className="button" disabled={busy} onClick={()=>setConfirmation({title:copy("Leave this project?","¿Salir del proyecto?"),description:copy("Your personal project stays available. You will need a new invitation to return.","Tu proyecto personal seguirá disponible. Necesitarás una nueva invitación para volver."),run:async()=>{await teamRequest(`/projects/${wid}/members/${encodeURIComponent(session?.user.id??"")}`,{action:"leave"});switchProject(null);}})}>{copy("Leave project","Salir del proyecto")}</button>}</div>
        </div>}
      </>}
    {invite&&<Dialog title={copy("Invite to project","Invitar al proyecto")} onClose={()=>{if(!busy)setInvite(false);}} className="team-dialog"><h2>{copy("Invite to project","Invitar al proyecto")}</h2><p>{project?.name}</p><form onSubmit={event=>{event.preventDefault();void run(()=>teamRequest(`/projects/${wid}/invitations`,{email,role:inviteRole,sharingAcknowledged:acknowledged}),copy("Invitation email sent.","Invitación enviada."),()=>setInvite(false));}}>
      <label className="team-field">{copy("Email","Correo electrónico")}<input type="email" autoFocus required maxLength={254} disabled={busy} value={email} onChange={e=>setEmail(e.target.value)}/></label>
      <label className="team-field">{copy("Role","Rol")}<Select value={inviteRole} onValueChange={setInviteRole} disabled={busy} options={[{value:"editor",label:copy("Editor","Editor"),description:copy("Can add and edit shared notes","Puede añadir y editar notas compartidas")},{value:"viewer",label:copy("Viewer","Lector"),description:copy("Can read shared notes and Flares","Puede leer notas compartidas y Flares")}]}/></label>
      <label className="team-sharing"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={e=>setAcknowledged(e.target.checked)}/><span>{copy("I understand that this person will see the project's existing shared materials, including imported content.","Entiendo que esta persona verá los materiales compartidos del proyecto, incluido el contenido importado.")}</span></label>
      {error&&<p role="alert" className="team-error">{error}</p>}<div className="team-actions"><button type="button" className="button" disabled={busy} onClick={()=>setInvite(false)}>{copy("Cancel","Cancelar")}</button><button className="button primary" disabled={busy||!acknowledged}>{busy?copy("Sending…","Enviando…"):copy("Send invitation","Enviar invitación")}</button></div></form></Dialog>}
    {confirmation&&<Dialog title={confirmation.title} onClose={()=>{if(!busy)setConfirmation(null);}} className="team-dialog"><h2>{confirmation.title}</h2><p>{confirmation.description}</p>
      {confirmation.kind==="transfer"?<div className="team-transfer-list">{members.filter(m=>m.id!==session?.user.id).map(m=><button className="button" disabled={busy} key={m.id} onClick={()=>void run(()=>teamRequest(`/projects/${wid}/members/${encodeURIComponent(m.id)}`,{action:"transfer"}),copy("Ownership transferred. Billing stays with the license owner.","Propiedad transferida. La facturación no cambia."),()=>setConfirmation(null))}>{m.name}</button>)}</div>
        :confirmation.kind==="rename"?<form onSubmit={e=>{e.preventDefault();void run(()=>teamRequest(`/projects/${wid}`,{name:projectName.trim()},"PATCH"),copy("Project renamed.","Nombre actualizado."),()=>setConfirmation(null));}}><label className="team-field">{copy("Project name","Nombre del proyecto")}<input autoFocus required maxLength={100} value={projectName} disabled={busy} onChange={e=>setProjectName(e.target.value)}/></label><div className="team-actions"><button type="button" className="button" disabled={busy} onClick={()=>setConfirmation(null)}>{copy("Cancel","Cancelar")}</button><button className="button primary" disabled={busy||!projectName.trim()}>{copy("Save","Guardar")}</button></div></form>
        :<div className="team-actions"><button className="button" disabled={busy} onClick={()=>setConfirmation(null)}>{copy("Cancel","Cancelar")}</button><button className="button primary" disabled={busy} onClick={()=>void run(confirmation.run,copy("Done.","Hecho."),()=>setConfirmation(null))}>{copy("Confirm","Confirmar")}</button></div>}
      {error&&<p role="alert" className="team-error">{error}</p>}
    </Dialog>}
  </section>;
}
