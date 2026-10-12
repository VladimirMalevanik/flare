"use client";
import { useEffect, useState } from "react";
import { useSession } from "@/components/auth-session";
import { Select } from "@/components/select";
import { Dialog } from "@/components/dialog";
import { teamRequest, type ProjectsResponse } from "./api";
import { selectedProject, switchProject } from "@/lib/team-context";
import { useI18n } from "@/i18n/provider";

export function ProjectMenu() {
  const session = useSession();
  const { locale } = useI18n();
  const es = locale === "es";
  const [data, setData] = useState<ProjectsResponse | null>(null);
  const [create, setCreate] = useState(false);
  const [name, setName] = useState("");
  const [requestId, setRequestId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void teamRequest<ProjectsResponse>("/projects", undefined, undefined, controller.signal).then(setData).catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    const open = () => { setRequestId(crypto.randomUUID()); setName(""); setError(""); setCreate(true); };
    window.addEventListener("flare:create-project", open);
    return () => window.removeEventListener("flare:create-project", open);
  }, []);
  if (!data || !session) return null;
  const value = selectedProject() ?? session.workspace.id;
  function choose(id: string) {
    if (id === "create") { setRequestId(crypto.randomUUID()); setCreate(true); return; }
    // Existing page beforeunload handlers can guard unsaved drafts.
    switchProject(data?.projects.find(p => p.id === id)?.kind === "personal" ? null : id);
  }
  async function save() {
    if (busy || !name.trim() || !data?.capability.canCreate) return;
    setBusy(true); setError("");
    try {
      const result = await teamRequest<{workspaceId:string}>("/projects", { id: requestId, name: name.trim() });
      switchProject(result.workspaceId, "/team");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not create project."); setBusy(false); }
  }
  return <div className="team-project-menu">
    <Select value={value} aria-label={es ? "Proyecto actual" : "Current project"} onValueChange={choose}
      options={[...data.projects.map(p => ({ value:p.id, label:p.name, description:p.kind === "team" ? (es ? "Proyecto de equipo" : "Team project") : (es ? "Personal" : "Personal") })),
        { value:"create", label:es ? "Crear proyecto" : "Create project", description:data.capability.canCreate ? "Team" : (es ? "Requiere Team" : "Requires Team") }]}/>
    {create && <Dialog title={es ? "Crear proyecto de equipo" : "Create team project"} onClose={() => { if (!busy) setCreate(false); }} className="team-dialog">
      <h2>{es ? "Crear proyecto de equipo" : "Create team project"}</h2>
      <p>{es ? "Un espacio vacío para tu equipo. Tus notas personales se mantienen privadas." : "An empty home for your team. Your personal notes stay private."}</p>
      {data.capability.canCreate ? <form onSubmit={e => { e.preventDefault(); void save(); }}>
        <label className="team-field">{es ? "Nombre del proyecto" : "Project name"}<input autoFocus value={name} maxLength={100} onChange={e => setName(e.target.value)} required disabled={busy}/></label>
        <p className="muted">{data.capability.limits.members} {es ? "miembros, propietario incluido" : "members, including the owner"}</p>
        {error && <p role="alert" className="team-error">{error}</p>}
        <div className="team-actions"><button type="button" className="button" disabled={busy} onClick={() => setCreate(false)}>{es ? "Cancelar" : "Cancel"}</button>
          <button className="button primary" disabled={busy || !name.trim()}>{busy ? (es ? "Creando…" : "Creating…") : (es ? "Crear proyecto" : "Create project")}</button></div>
      </form> : <>
        <p>{data.capability.requiresVerification ? (es ? "Confirma tu correo desde la sección Equipo antes de crear un proyecto." : "Verify your email in Team before creating a project.")
          : data.capability.projectCount >= data.capability.limits.projects ? (es ? "Tu suscripción ha alcanzado el límite de proyectos." : "Your subscription has reached its project limit.")
          : (es ? "Necesitas una suscripción Team activa para crear un proyecto. Los invitados no necesitan su propia suscripción." : "You need an active Team subscription to create a project. Invited members do not need their own subscription.")}</p>
        <div className="team-actions"><button className="button" onClick={() => setCreate(false)}>{es ? "Cerrar" : "Close"}</button>
          <a className="button primary" href="/settings#subscription">{es ? "Ver suscripción" : "View subscription"}</a></div>
      </>}
    </Dialog>}
  </div>;
}
