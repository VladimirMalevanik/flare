"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { apiBaseUrl, authRequest, type Session } from "@/lib/auth/session";
import { teamRequest, type ProjectsResponse, TeamError } from "./api";
import { switchProject } from "@/lib/team-context";
import { BrandMark } from "@/components/brand-mark";
import { useI18n } from "@/i18n/provider";
const key="flare-team-invitation";

export function JoinPage() {
  const {locale}=useI18n();const es=locale==="es";const copy=(en:string,spanish:string)=>es?spanish:en;
  const [token,setToken]=useState("");const [session,setSession]=useState<Session|null>(null);
  const [loading,setLoading]=useState(true);const [busy,setBusy]=useState(false);const [error,setError]=useState("");
  const [verification,setVerification]=useState(false);const [notice,setNotice]=useState("");const [accept,setAccept]=useState(false);
  const [preview,setPreview]=useState<{projectName:string;invitedBy:string|null;role:string;expiresAt:string}|null>(null);
  useEffect(()=>{
    const controller=new AbortController();
    async function load() {
      let candidate=window.location.hash.slice(1);
      try {
        if(/^[A-Za-z0-9_-]{43}$/.test(candidate)) sessionStorage.setItem(key,JSON.stringify({token:candidate,expires:Date.now()+30*60*1000}));
        else {const saved=JSON.parse(sessionStorage.getItem(key)??"null");if(saved&&saved.expires>Date.now()&&/^[A-Za-z0-9_-]{43}$/.test(saved.token))candidate=saved.token;}
      }catch { /* A valid fragment still works when browser storage is unavailable. */ }
      if(!/^[A-Za-z0-9_-]{43}$/.test(candidate))throw new Error(copy("Open the invitation link from your email.","Abre el enlace de invitación de tu correo."));
      setToken(candidate);
      const response=await fetch(`${apiBaseUrl}/auth/me`,{credentials:"include",cache:"no-store",signal:controller.signal});
      if(response.status===401)return;
      if(!response.ok)throw new Error(copy("Your account could not be checked. Please retry.","No se pudo verificar tu cuenta. Reinténtalo."));
      const user:Session=await response.json();setSession(user);
      if(user.user.emailVerified&&user.user.legalAccepted){const result=await teamRequest<ProjectsResponse>("/projects",undefined,undefined,controller.signal);setVerification(result.capability.requiresVerification);
        if(!result.capability.requiresVerification)setPreview(await teamRequest("/invitations/preview",{token:candidate},undefined,controller.signal));}
      else setVerification(!user.user.emailVerified);
    }
    void load().catch(cause=>{if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"Invitation unavailable.");}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[]);
  async function join() {
    if(busy||!accept||!session||verification)return;setBusy(true);setError("");
    try{const result=await teamRequest<{workspaceId:string}>("/invitations/accept",{token,accept:true});
      try{sessionStorage.removeItem(key);}catch{}
      window.history.replaceState(null,"","/join");switchProject(result.workspaceId,"/team");
    }catch(cause){setError(cause instanceof Error?cause.message:"Invitation unavailable.");if(cause instanceof TeamError&&cause.status===403)setVerification(true);setBusy(false);}
  }
  async function verify() {
    if(busy)return;setBusy(true);setError("");
    try{if(session&&!session.user.emailVerified)await authRequest("resend-verification",{email:session.user.email});
      else await teamRequest("/verify-email",{});
      setNotice(copy("Check your email to verify this address, then return to this invitation link.","Confirma tu dirección desde el correo y vuelve al enlace de invitación."));
    }catch(cause){setError(cause instanceof Error?cause.message:"Could not send verification.");}finally{setBusy(false);}
  }
  return <main className="team-join"><Link href="/" className="brand"><BrandMark size={30}/><strong>Flare</strong></Link><section className="card team-join-card"><h1>{copy("Join a team project","Únete a un proyecto de equipo")}</h1><p>{copy("Use the email address that received the invitation. Your personal project will remain separate.","Usa la dirección que recibió la invitación. Tu proyecto personal seguirá separado.")}</p>
    {loading?<p role="status">{copy("Checking your account…","Verificando tu cuenta…")}</p>:!session?<div className="team-actions"><a className="button" href="/register">{copy("Create account","Crear cuenta")}</a><a className="button primary" href="/login">{copy("Sign in","Iniciar sesión")}</a></div>:<>
      <p className="team-join-account">{copy("Signed in as","Sesión iniciada como")} <strong>{session.user.email}</strong></p>
      {preview&&<div className="team-feedback"><strong>{preview.projectName}</strong><p>{copy("Invited by","Invitación de")} {preview.invitedBy??"Flare"} · {preview.role==="editor"?copy("Editor","Editor"):copy("Viewer","Lector")}</p></div>}
      {!session.user.legalAccepted?<a className="button primary" href="/legal-acceptance">{copy("Review terms","Revisar condiciones")}</a>:verification?<button className="button primary" disabled={busy} onClick={()=>void verify()}>{copy("Verify this email","Verificar este correo")}</button>:<>
        <label className="team-sharing"><input type="checkbox" checked={accept} disabled={busy} onChange={e=>setAccept(e.target.checked)}/><span>{copy("I accept the invitation and understand that this project contains materials shared with its members.","Acepto la invitación y entiendo que el proyecto contiene materiales compartidos con sus miembros.")}</span></label>
        <button className="button primary" disabled={busy||!accept||!token||!preview} onClick={()=>void join()}>{busy?copy("Joining…","Uniéndote…"):copy("Join project","Unirse al proyecto")}</button></>}
      <button className="button ghost" disabled={busy} onClick={async()=>{setBusy(true);try{await authRequest("logout");window.location.replace("/login");}catch(cause){setError(cause instanceof Error?cause.message:"Could not sign out.");setBusy(false);}}}>{copy("Use a different account","Usar otra cuenta")}</button>
    </>}
    {notice&&<p role="status" className="team-feedback">{notice}</p>}{error&&<p role="alert" className="team-error">{error}</p>}
    {!loading&&<div className="team-actions"><button className="button ghost" disabled={busy} onClick={()=>window.location.reload()}>{copy("Check again","Comprobar de nuevo")}</button>
      <button className="button ghost" disabled={busy} onClick={()=>{try{sessionStorage.removeItem(key);}catch{}window.location.replace("/vault");}}>{copy("Not now","Ahora no")}</button></div>}
  </section></main>;
}
