"use client";

import { useEffect } from "react";
import { attachLandingMotion } from "@/lib/landing-motion";

export function LandingMotion() {
  useEffect(() => {
    const root = document.querySelector<HTMLElement>(".landing-page");
    if (!root) return;
    const motion = attachLandingMotion(root);
    return () => motion.dispose();
  }, []);

  return null;
}
