"use client";

import { useEffect } from "react";
import { useWorkspace } from "@/components/workspace-context";
import { playFunnySound, stopFunnySounds } from "./funny-sounds";

export function FunnyEffects() {
  const { funnyMode, funnySounds, funnyAudioPaused } = useWorkspace();
  useEffect(() => {
    if (!funnyMode || !funnySounds || funnyAudioPaused) {
      stopFunnySounds();
      return;
    }
    let lastClickAt = 0;
    const click = (event: MouseEvent) => {
      if (!event.isTrusted || document.hidden || !(event.target instanceof Element)) return;
      if (event.target.closest('[data-funny-sound="off"]')) return;
      const control = event.target.closest('button, a[href], input[type="checkbox"], input[type="radio"], [role="switch"]');
      if (!control || control.matches(':disabled, [aria-disabled="true"]')) return;
      const now = performance.now();
      if (now - lastClickAt < 120) return;
      lastClickAt = now;
      playFunnySound("click", true);
    };
    const visibility = () => { if (document.hidden) stopFunnySounds(); };
    document.addEventListener("click", click, true);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      document.removeEventListener("click", click, true);
      document.removeEventListener("visibilitychange", visibility);
      stopFunnySounds();
    };
  }, [funnyMode, funnySounds, funnyAudioPaused]);
  return null;
}
