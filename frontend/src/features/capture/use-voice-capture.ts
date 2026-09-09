"use client";
import { useEffect, useState } from "react";
import { VoiceRecorder, type VoiceSnapshot } from "./voice-recorder";

export function useVoiceCapture() {
  const [snapshot, setSnapshot] = useState<VoiceSnapshot>({ state: "idle", recording: null, error: "" });
  const [controller] = useState(() => new VoiceRecorder(setSnapshot));
  const [seconds, setSeconds] = useState(0);
  useEffect(() => () => controller.dispose(), [controller]);
  useEffect(() => {
    if (snapshot.state !== "recording") return;
    const started = Date.now();
    const interval = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 250);
    return () => clearInterval(interval);
  }, [snapshot.state]);
  const start = () => {
    setSeconds(0);
    return controller.start();
  };
  return { ...snapshot, seconds, start, stop: controller.stop, cancel: controller.cancel };
}
