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
  const copy = (en: string, spanish: string) => es ? spanish : en;
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
    let live = true;
    const refresh = () => { void teamRequest<ProjectsResponse>("/projects").then(value => { if(live)setData(value); }).catch(()=>{}); };
    window.addEventListener("focus",refresh);
    window.addEventListener("flare:team-refresh",refresh);
    return () => { live=false;window.removeEventListener("focus",refresh);window.removeEventListener("flare:team-refresh",refresh); };
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
    switchProject(id);
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
    <Select value={value} aria-label={copy("Current project", "Proyecto actual")} onValueChange={choose}
      options={[...data.projects.map(p => ({ value:p.id, label:p.name, description:p.kind === "team" ? copy("Team project", "Proyecto de equipo") : p.kind === "shared" ? copy("Shared project", "Proyecto compartido") : copy("Personal", "Personal") })),
        { value:"create", label:copy("Create project", "Crear proyecto"), description:data.capability.canCreate ? "Team" : (copy("Requires Team", "Requiere Team")) }]}/>
    {create && <Dialog title={copy("Create team project", "Crear proyecto de equipo")} onClose={() => { if (!busy) setCreate(false); }} className="team-dialog">
      <h2>{copy("Create team project", "Crear proyecto de equipo")}</h2>
      <p>{copy("An empty home for your team. Your personal notes stay private.", "Un espacio vacío para tu equipo. Tus notas personales se mantienen privadas.")}</p>
      {data.capability.canCreate ? <form onSubmit={e => { e.preventDefault(); void save(); }}>
        <label className="team-field">{copy("Project name", "Nombre del proyecto")}<input autoFocus value={name} maxLength={100} onChange={e => setName(e.target.value)} required disabled={busy}/></label>
        <p className="muted">{data.capability.limits.members} {copy("members, including the owner", "miembros, propietario incluido")}</p>
        {error && <p role="alert" className="team-error">{error}</p>}
        <div className="team-actions"><button type="button" className="button" disabled={busy} onClick={() => setCreate(false)}>{copy("Cancel", "Cancelar")}</button>
          <button className="button primary" disabled={busy || !name.trim()}>{busy ? (copy("Creating…", "Creando…")) : (copy("Create project", "Crear proyecto"))}</button></div>
      </form> : <>
        <p>{data.capability.requiresVerification ? (copy("Verify your email in Team before creating a project.", "Confirma tu correo desde la sección Equipo antes de crear un proyecto."))
          : data.capability.projectCount >= data.capability.limits.projects ? (copy("Your subscription has reached its project limit.", "Tu suscripción ha alcanzado el límite de proyectos."))
          : (copy("You need an active Team subscription to create a project. Invited members do not need their own subscription.", "Necesitas una suscripción Team activa para crear un proyecto. Los invitados no necesitan su propia suscripción."))}</p>
        <div className="team-actions"><button className="button" onClick={() => setCreate(false)}>{copy("Close", "Cerrar")}</button>
          <a className="button primary" href="/settings#subscription">{copy("View subscription", "Ver suscripción")}</a></div>
      </>}
    </Dialog>}
  </div>;
}
