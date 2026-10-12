"use client";
import { useEffect, useRef, useState } from "react";
import { useSession } from "@/components/auth-session";
import { Select } from "@/components/select";
import { Dialog } from "@/components/dialog";
import { Icon } from "@/components/icons";
import { useI18n } from "@/i18n/provider";
import { switchProject } from "@/lib/team-context";
import { teamRequest, type ProjectsResponse, type Member, type Invitation, type Task, type History } from "./api";

type Confirmation = { title:string; description:string; run:()=>Promise<unknown> };
export function TeamPage() {
  const session = useSession(); const { locale } = useI18n(); const es = locale === "es";
  const copy = (en:string, spanish:string) => es ? spanish : en;
  const wid = session?.workspace.id;
  const [data,setData] = useState<ProjectsResponse | null>(null);
  const [members,setMembers] = useState<Member[]>([]);
  const [invitations,setInvitations] = useState<Invitation[]>([]);
  const [tasks,setTasks] = useState<Task[]>([]);
  const [cursor,setCursor] = useState<{beforeAt:string;beforeId:string}|null>(null);
  const [tab,setTab] = useState("tasks"); const [filter,setFilter] = useState("all");
  const [error,setError] = useState(""); const [notice,setNotice] = useState("");
  const [loading,setLoading] = useState(true); const [busy,setBusy] = useState(false);
  const lock=useRef(false);
  const [invite,setInvite] = useState(false); const [email,setEmail] = useState(""); const [inviteRole,setInviteRole] = useState("editor");
  const [acknowledged,setAcknowledged] = useState(false);
  const [editing,setEditing] = useState<Task | "new" | null>(null);
  const [title,setTitle] = useState(""); const [description,setDescription] = useState("");
  const [status,setStatus] = useState("todo"); const [assignee,setAssignee] = useState("");
  const [taskId,setTaskId] = useState(""); const [history,setHistory] = useState<History[] | null>(null);
  const [confirmation,setConfirmation] = useState<Confirmation | null>(null);
  const project=data?.projects.find(p=>p.id===wid);
  const owner=project?.role==="owner"; const writable=project?.writable && project.role!=="viewer";
  const date=(value:string)=>new Date(value).toLocaleString(locale,{dateStyle:"medium",timeStyle:"short"});
  const taskLabel=(value:string)=>value==="todo" ? copy("To do","Por hacer") : value==="doing" ? copy("In progress","En curso") : copy("Done","Hecho");

  async function reload(signal?:AbortSignal) {
    const result=await teamRequest<ProjectsResponse>("/projects",undefined,undefined,signal); setData(result);
    const p=result.projects.find(p=>p.id===wid);
    if(p?.kind==="team") {
      const [people,items]=await Promise.all([teamRequest<Member[]>(`/projects/${wid}/members`,undefined,undefined,signal),
        teamRequest<{tasks:Task[];nextCursor:typeof cursor}>(`/projects/${wid}/tasks`,undefined,undefined,signal)]);
      setMembers(people);setTasks(items.tasks);setCursor(items.nextCursor);
      if(p.role==="owner") setInvitations(await teamRequest<Invitation[]>(`/projects/${wid}/invitations`,undefined,undefined,signal));
      else setInvitations([]);
    }
  }
  useEffect(()=>{
    const controller=new AbortController();
    void reload(controller.signal).catch(cause=>{if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Team could not load.");})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
    // One component instance belongs to one validated project.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[wid]);
  useEffect(()=>{
    if(!editing && !invite)return;
    const guard=(event:BeforeUnloadEvent)=>{if(title||description||email){event.preventDefault();event.returnValue="";}};
    window.addEventListener("beforeunload",guard);return()=>window.removeEventListener("beforeunload",guard);
  },[editing,invite,title,description,email]);

  async function run(action:()=>Promise<unknown>,done:string,onSuccess?:()=>void) {
    if(lock.current)return;lock.current=true;setBusy(true);setError("");setNotice("");
    try{await action();onSuccess?.();setNotice(done);await reload();}
    catch(cause){setError(cause instanceof Error?cause.message:copy("This action could not complete.","No se pudo completar esta acción."));}
    finally{lock.current=false;setBusy(false);}
  }
  function edit(task:Task|"new") {
    setError("");setEditing(task);setTitle(task==="new"?"":task.title);setDescription(task==="new"?"":task.description);
    setStatus(task==="new"?"todo":task.status);setAssignee(task==="new"?"":task.assigneeId??"");setTaskId(task==="new"?crypto.randomUUID():task.id);setHistory(null);
  }
  function closeEdit() {
    if(busy)return;
    const changed=editing==="new"?Boolean(title||description):editing && (title!==editing.title||description!==editing.description||status!==editing.status||assignee!==(editing.assigneeId??""));
    if(changed){setConfirmation({title:copy("Discard this draft?","¿Descartar este borrador?"),description:copy("Your unsaved changes will be lost.","Se perderán los cambios sin guardar."),run:async()=>{setEditing(null);}});return;}
    setEditing(null);
  }
  async function more() {
    if(!cursor||busy)return;setBusy(true);
    try{const result=await teamRequest<{tasks:Task[];nextCursor:typeof cursor}>(`/projects/${wid}/tasks?beforeAt=${encodeURIComponent(cursor.beforeAt)}&beforeId=${encodeURIComponent(cursor.beforeId)}`);
      setTasks(previous=>[...previous,...result.tasks.filter(t=>!previous.some(p=>p.id===t.id))]);setCursor(result.nextCursor);}
    catch(cause){setError(cause instanceof Error?cause.message:"Could not load tasks.");}finally{setBusy(false);}
  }
  const visible=tasks.filter(t=>filter==="all"||filter==="mine"&&t.assigneeId===session?.user.id||filter===t.status);
  return <section className="page team-page">
    <header className="page-heading"><h1>{project?.kind==="team"?project.name:"Team"}</h1><p>{copy("Work from the same context, with your own accounts.","Comparte contexto con tu equipo, cada uno con su cuenta.")}</p></header>
    {error&&!editing&&!invite&&<p role="alert" className="team-feedback team-error">{error}</p>}
    {notice&&<p role="status" className="team-feedback">{notice}</p>}
    {loading?<p role="status">{copy("Loading your team…","Cargando tu equipo…")}</p>:!data?<div className="card team-empty"><h2>{copy("Team is not enabled yet","Team aún no está habilitado")}</h2><p>{copy("Your existing project is available. Team needs its billing and email configuration before launch.","Tu proyecto sigue disponible. Team requiere configurar pagos y correo antes de activarlo.")}</p><button className="button" onClick={()=>void run(()=>reload(),"")}>{copy("Try again","Reintentar")}</button></div>
      :project?.kind!=="team"?<div className="card team-empty"><Icon name="sources"/><h2>{copy("A shared project for your team","Un proyecto compartido para tu equipo")}</h2><p>{copy("Create an empty team project and invite colleagues by email. Personal notes stay in personal projects.","Crea un proyecto vacío e invita a tus compañeros por correo. Las notas personales permanecen en los proyectos personales.")}</p>
        <p className="muted">{copy(`Your Team license includes up to ${data.capability.limits.members} members. Only the owner needs the subscription.`,`Tu licencia Team incluye hasta ${data.capability.limits.members} miembros. Solo el propietario necesita la suscripción.`)}</p>
        {data.capability.requiresVerification&&<button className="button" disabled={busy} onClick={()=>void run(()=>teamRequest("/verify-email",{}),copy("Verification email sent. Open its link, then refresh this page.","Correo de verificación enviado. Abre el enlace y actualiza esta página."))}>{copy("Verify my email","Verificar mi correo")}</button>}
        <div className="team-actions"><a className="button" href="/settings#subscription">{copy("View subscription","Ver suscripción")}</a>
          <button className="button primary" onClick={()=>window.dispatchEvent(new Event("flare:create-project"))}>{copy("Create team project","Crear proyecto de equipo")}</button></div>
      </div>:<>
        {!project.writable&&<div className="team-feedback" role="status">{copy("This project is read-only. Your materials are preserved; the license owner can renew Team to continue adding content.","Este proyecto es de solo lectura. Tus materiales se conservan; el propietario de la licencia puede renovar Team para añadir contenido.")}</div>}
        <div className="team-toolbar"><div className="team-tabs" role="group" aria-label={copy("Team views","Vistas del equipo")}>
          <button className={tab==="tasks"?"button active":"button"} aria-pressed={tab==="tasks"} onClick={()=>setTab("tasks")}>{copy("Tasks","Tareas")}</button>
          <button className={tab==="members"?"button active":"button"} aria-pressed={tab==="members"} onClick={()=>setTab("members")}>{copy("Members","Miembros")} <span className="muted">{members.length}/{data.capability.limits.members}</span></button></div>
          {tab==="tasks"?<button className="button primary" disabled={!writable||busy} onClick={()=>edit("new")}><Icon name="plus"/>{copy("Add task","Añadir tarea")}</button>
            :owner&&<button className="button primary" disabled={!project.writable||busy} onClick={()=>{setEmail("");setAcknowledged(false);setError("");setInvite(true);}}><Icon name="plus"/>{copy("Invite member","Invitar miembro")}</button>}
        </div>
        {tab==="tasks"?<>
          <div className="team-task-toolbar"><Select value={filter} onValueChange={setFilter} aria-label={copy("Filter tasks","Filtrar tareas")} variant="compact" options={[{value:"all",label:copy("All tasks","Todas las tareas")},{value:"mine",label:copy("Assigned to me","Asignadas a mí")},...['todo','doing','done'].map(s=>({value:s,label:taskLabel(s)}))]}/>
            <span className="muted">{tasks.length} {copy("loaded","cargadas")}</span><button className="button ghost" disabled={busy} onClick={()=>void run(()=>reload(),"")}>{copy("Refresh","Actualizar")}</button></div>
          <div className="team-task-list">{visible.length===0?<div className="card team-empty"><h2>{copy("No tasks here yet","Aún no hay tareas aquí")}</h2><p>{copy("Add a task, choose an assignee and keep progress visible to your team.","Añade una tarea, elige un responsable y comparte el progreso con tu equipo.")}</p></div>
            :visible.map(task=><button key={task.id} className="card team-task" onClick={()=>edit(task)}><span className={`team-task-status ${task.status}`}>{taskLabel(task.status)}</span><strong>{task.title}</strong>
              {task.description&&<span className="team-task-description">{task.description}</span>}
              <span className="team-task-meta"><span>{copy("Added by","Añadida por")} <b>{task.creatorName}</b></span><span>{copy("Assigned to","Responsable")}: {task.assigneeName??copy("Unassigned","Sin asignar")}</span><time dateTime={task.createdAt}>{date(task.createdAt)}</time></span></button>)}</div>
          {cursor&&<button className="button team-load-more" disabled={busy} onClick={()=>void more()}>{copy("Load more tasks","Cargar más tareas")}</button>}
        </>:<div className="card team-members"><h2>{copy("Project members","Miembros del proyecto")}</h2>
          {members.map(member=><div className="team-member" key={member.id}><div className="team-avatar" aria-hidden="true">{member.name.slice(0,1).toUpperCase()}</div><div className="team-member-copy"><strong>{member.name}{member.id===session?.user.id?copy(" · You"," · Tú"):""}</strong>{member.email&&<small>{member.email}</small>}</div>
            {owner&&member.role!=="owner"?<><Select value={member.role} onValueChange={role=>void run(()=>teamRequest(`/projects/${wid}/members/${encodeURIComponent(member.id)}`,{action:"role",role}),copy("Role updated.","Rol actualizado."))} disabled={busy} variant="compact" aria-label={copy(`Role for ${member.name}`,`Rol de ${member.name}`)} options={[{value:"editor",label:copy("Editor","Editor")},{value:"viewer",label:copy("Viewer","Lector")}]}/>
              <button className="button ghost" disabled={busy} onClick={()=>setConfirmation({title:copy("Remove this member?","¿Eliminar este miembro?"),description:copy(`${member.name} will lose access to this project. Shared materials will stay.`,`${member.name} perderá acceso al proyecto. Los materiales compartidos se conservarán.`),run:()=>teamRequest(`/projects/${wid}/members/${encodeURIComponent(member.id)}`,{action:"remove"})})}>{copy("Remove","Eliminar")}</button></>
              :<span className="team-role">{member.role==="owner"?copy("Owner","Propietario"):member.role==="editor"?copy("Editor","Editor"):copy("Viewer","Lector")}</span>}</div>)}
          {owner&&<><h3>{copy("Invitations","Invitaciones")}</h3><p className="muted">{copy("Pending invitations reserve a seat and expire after seven days.","Las invitaciones pendientes reservan una plaza y caducan después de siete días.")}</p>
            {invitations.length===0?<p className="team-empty-copy">{copy("No invitations yet.","Aún no hay invitaciones.")}</p>:invitations.map(inv=><div className="team-member" key={inv.id}><div className="team-member-copy"><strong>{inv.email}</strong><small>{inv.status} · {inv.role} · {date(inv.expiresAt)}</small></div>
              {inv.status==="pending"&&<><button className="button ghost" disabled={busy||!project.writable} onClick={()=>{setEmail(inv.email);setInviteRole(inv.role);setAcknowledged(false);setError("");setInvite(true);}}>{copy("Send again","Reenviar")}</button>
                <button className="button ghost" disabled={busy} onClick={()=>void run(()=>teamRequest(`/projects/${wid}/invitations/${inv.id}`,undefined,"DELETE"),copy("Invitation canceled.","Invitación cancelada."))}>{copy("Cancel","Cancelar")}</button></>}</div>)}</>}
          <div className="team-members-footer">{owner?<button className="button" disabled={busy||members.length<2} onClick={()=>setConfirmation({title:copy("Transfer project ownership","Transferir propiedad del proyecto"),description:copy("Choose an existing member below. Billing remains with the original license owner.","Elige un miembro. La facturación permanece con el propietario original de la licencia."),run:async()=>{}})}>{copy("Transfer ownership","Transferir propiedad")}</button>
            :<button className="button" disabled={busy} onClick={()=>setConfirmation({title:copy("Leave this project?","¿Salir del proyecto?"),description:copy("Your personal project stays available. You will need a new invitation to return.","Tu proyecto personal seguirá disponible. Necesitarás una nueva invitación para volver."),run:async()=>{await teamRequest(`/projects/${wid}/members/${encodeURIComponent(session?.user.id??"")}`,{action:"leave"});switchProject(null);}})}>{copy("Leave project","Salir del proyecto")}</button>}</div>
        </div>}
      </>}
    {invite&&<Dialog title={copy("Invite to project","Invitar al proyecto")} onClose={()=>{if(!busy)setInvite(false);}} className="team-dialog"><h2>{copy("Invite to project","Invitar al proyecto")}</h2><p>{project?.name}</p><form onSubmit={event=>{event.preventDefault();void run(()=>teamRequest(`/projects/${wid}/invitations`,{email,role:inviteRole,sharingAcknowledged:acknowledged}),copy("Invitation email sent.","Invitación enviada."),()=>setInvite(false));}}>
      <label className="team-field">Email<input type="email" autoFocus required maxLength={254} disabled={busy} value={email} onChange={e=>setEmail(e.target.value)}/></label>
      <label className="team-field">{copy("Role","Rol")}<Select value={inviteRole} onValueChange={setInviteRole} disabled={busy} options={[{value:"editor",label:copy("Editor","Editor"),description:copy("Can add and edit context and tasks","Puede añadir y editar contexto y tareas")},{value:"viewer",label:copy("Viewer","Lector"),description:copy("Can read project materials and tasks","Puede leer materiales y tareas")}]}/></label>
      <label className="team-sharing"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={e=>setAcknowledged(e.target.checked)}/><span>{copy("I understand that this person will see the project's existing shared materials, including imported content.","Entiendo que esta persona verá los materiales compartidos del proyecto, incluido el contenido importado.")}</span></label>
      {error&&<p role="alert" className="team-error">{error}</p>}<div className="team-actions"><button type="button" className="button" disabled={busy} onClick={()=>setInvite(false)}>{copy("Cancel","Cancelar")}</button><button className="button primary" disabled={busy||!acknowledged}>{busy?copy("Sending…","Enviando…"):copy("Send invitation","Enviar invitación")}</button></div></form></Dialog>}
    {editing&&!confirmation&&<Dialog title={copy("Project task","Tarea del proyecto")} onClose={closeEdit} className="team-dialog"><h2>{editing==="new"?copy("Add task","Añadir tarea"):copy("Project task","Tarea del proyecto")}</h2>
      {editing!=="new"&&<p className="muted">{copy("Added by","Añadida por")} {editing.creatorName} · {date(editing.createdAt)}</p>}
      <form onSubmit={e=>{e.preventDefault();if(!writable)return;void run(()=>teamRequest(`/projects/${wid}/tasks`,{id:taskId,expectedVersion:editing==="new"?0:editing.version,title,description,status,assigneeId:assignee||null}),copy("Task saved.","Tarea guardada."),()=>setEditing(null));}}>
        <label className="team-field">{copy("Title","Título")}<input autoFocus required maxLength={180} value={title} disabled={busy||!writable} onChange={e=>setTitle(e.target.value)}/></label>
        <label className="team-field">{copy("Description","Descripción")}<textarea rows={4} maxLength={10000} value={description} disabled={busy||!writable} onChange={e=>setDescription(e.target.value)}/></label>
        <div className="team-form-row"><label className="team-field">{copy("Status","Estado")}<Select value={status} onValueChange={setStatus} disabled={busy||!writable} options={['todo','doing','done'].map(s=>({value:s,label:taskLabel(s)}))}/></label>
          <label className="team-field">{copy("Assignee","Responsable")}<Select value={assignee} onValueChange={setAssignee} disabled={busy||!writable} options={[{value:"",label:copy("Unassigned","Sin asignar")},...members.map(m=>({value:m.id,label:m.name}))]}/></label></div>
        {error&&<div role="alert" className="team-error"><p>{error}</p>{editing!=="new"&&<button type="button" className="button" disabled={busy} onClick={()=>void run(async()=>{const fresh=await teamRequest<{tasks:Task[]}>(`/projects/${wid}/tasks`);const task=fresh.tasks.find(t=>t.id===taskId);if(!task)throw new Error("Task not available in the current page; refresh the list.");setEditing(task);},copy("Latest version loaded. Your draft is still in the form; review it before saving.","Versión actual cargada. Tu borrador sigue en el formulario; revísalo antes de guardar."))}>{copy("Load latest version, keep draft","Cargar versión actual, conservar borrador")}</button>}</div>}
        <div className="team-actions"><button type="button" className="button" disabled={busy} onClick={closeEdit}>{copy("Close","Cerrar")}</button>{writable&&<button className="button primary" disabled={busy||!title.trim()}>{busy?copy("Saving…","Guardando…"):copy("Save task","Guardar tarea")}</button>}</div>
      </form>
      {editing!=="new"&&<div className="team-task-tools"><button className="button ghost" disabled={busy} onClick={()=>void run(async()=>setHistory(await teamRequest<History[]>(`/projects/${wid}/tasks/${taskId}/history`)),"")}>{copy("View history","Ver historial")}</button>
        {writable&&<button className="button ghost" disabled={busy} onClick={()=>setConfirmation({title:copy("Delete this task?","¿Eliminar esta tarea?"),description:copy("It will be removed from the task list. Its author and history are preserved.","Se eliminará de la lista. Se conservarán el autor y el historial."),run:async()=>{await teamRequest(`/projects/${wid}/tasks`,{id:taskId,expectedVersion:editing.version,remove:true});setEditing(null);}})}>{copy("Delete task","Eliminar tarea")}</button>}</div>}
      {history&&<ol className="team-history">{history.map((h,i)=><li key={i}><strong>{h.actorName}</strong> · {h.action}<small>{h.fields.join(", ")} · {date(h.createdAt)}</small></li>)}</ol>}
    </Dialog>}
    {confirmation&&<Dialog title={confirmation.title} onClose={()=>{if(!busy)setConfirmation(null);}} className="team-dialog"><h2>{confirmation.title}</h2><p>{confirmation.description}</p>
      {confirmation.title===copy("Transfer project ownership","Transferir propiedad del proyecto")?<div className="team-transfer-list">{members.filter(m=>m.id!==session?.user.id).map(m=><button className="button" disabled={busy} key={m.id} onClick={()=>void run(()=>teamRequest(`/projects/${wid}/members/${encodeURIComponent(m.id)}`,{action:"transfer"}),copy("Ownership transferred. Billing stays with the license owner.","Propiedad transferida. La facturación no cambia."),()=>setConfirmation(null))}>{m.name}</button>)}</div>
        :<div className="team-actions"><button className="button" disabled={busy} onClick={()=>setConfirmation(null)}>{copy("Cancel","Cancelar")}</button><button className="button primary" disabled={busy} onClick={()=>void run(confirmation.run,copy("Done.","Hecho."),()=>setConfirmation(null))}>{copy("Confirm","Confirmar")}</button></div>}
      {error&&<p role="alert" className="team-error">{error}</p>}
    </Dialog>}
  </section>;
}
