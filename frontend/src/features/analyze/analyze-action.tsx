"use client";
import { useEffect, useRef, useState } from "react";
import { useSession } from "@/components/auth-session";
import { useWorkspace } from "@/components/workspace-context";
import { dataProvider, dataProviderMode } from "@/lib/data";
import { AnalyzeController, type AnalyzeState } from "./analyze-controller";

export function AnalyzeAction() {
  const session = useSession();
  const { refresh } = useWorkspace();
  const refreshRef = useRef(refresh);
  useEffect(() => { refreshRef.current = refresh; }, [refresh]);
  const [state, setState] = useState<AnalyzeState>({ busy: false, run: null, message: "", error: false });
  const controller = useRef<AnalyzeController | null>(null);
  useEffect(() => {
    const active = new AnalyzeController(dataProvider, setState, () => refreshRef.current());
    controller.current = active;
    return () => { active.dispose(); controller.current = null; };
  }, []);
  const viewer = session?.workspace.role === "viewer";
  const pending = state.run && ["pending", "processing"].includes(state.run.status);
  return (
    <div className="analyze-action">
      <button className="button primary" disabled={state.busy || viewer} onClick={() => void controller.current?.start()}>
        {state.busy ? "Analyzing…" : pending ? "Check status" : state.error ? "Retry Analyze" : "Analyze"}
      </button>
      <p className={state.error ? "error-text meta" : "muted meta"} role={state.error ? "alert" : "status"}>
        {viewer ? "Only owners and editors can analyze context." : state.message || "Analyze your recent project Notes to find Flares."}
        {dataProviderMode === "mock" && " Demo mode."}
      </p>
    </div>
  );
}
