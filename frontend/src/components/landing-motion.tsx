"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/provider";
import { attachLandingMotion } from "@/lib/landing-motion";

export function LandingMotion() {
  const { t } = useI18n();
  const button = useRef<HTMLButtonElement>(null);
  const controller = useRef<ReturnType<typeof attachLandingMotion> | null>(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const root = button.current?.closest<HTMLElement>(".landing-page");
    if (!root) return;
    const motion = attachLandingMotion(root);
    controller.current = motion;
    return () => { motion.dispose(); controller.current = null; };
  }, []);

  useEffect(() => { controller.current?.setPaused(paused); }, [paused]);

  return <button ref={button} type="button" className="landing-motion-control" aria-pressed={paused}
    onClick={() => setPaused((value) => !value)}>
    <span aria-hidden="true">{paused ? "▷" : "Ⅱ"}</span>
    {paused ? t("Resume animations") : t("Pause animations")}
  </button>;
}
