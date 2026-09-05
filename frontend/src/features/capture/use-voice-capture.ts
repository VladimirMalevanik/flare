"use client";
import { useEffect, useRef, useState } from "react";

export function useVoiceCapture(onTranscript: (text: string) => void) {
  const [state, setState] = useState<
    "idle" | "requesting" | "recording" | "transcribing"
  >("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const generation = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const release = () => {
    if (recorder.current?.state === "recording") recorder.current.stop();
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    recorder.current = null;
  };
  const cancel = () => {
    generation.current += 1;
    release();
    if (timer.current) clearTimeout(timer.current);
    setState("idle");
    setError("");
  };
  useEffect(
    () => () => {
      generation.current += 1;
      release();
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  useEffect(() => {
    if (state !== "recording") return;
    const started = Date.now();
    const interval = setInterval(
      () => setSeconds(Math.floor((Date.now() - started) / 1000)),
      250,
    );
    return () => clearInterval(interval);
  }, [state]);
  const transcribe = () => {
    generation.current += 1;
    release();
    setError("");
    setState("transcribing");
    timer.current = setTimeout(() => {
      onTranscript(
        "Demo transcript: Review the mobile sync contract and confirm expected retry behavior with the team.",
      );
      setState("idle");
    }, 1100);
  };
  const start = async () => {
    if (state !== "idle") return;
    const id = ++generation.current;
    setError("");
    setSeconds(0);
    setState("requesting");
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof MediaRecorder === "undefined"
      )
        throw new Error("Unavailable");
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (id !== generation.current) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      stream.current = media;
      const next = new MediaRecorder(media);
      recorder.current = next;
      next.onerror = () => {
        release();
        setState("idle");
        setError(
          "Recording interrupted. Try again or use the demo transcript.",
        );
      };
      next.start();
      setState("recording");
    } catch {
      if (id !== generation.current) return;
      release();
      setState("idle");
      setError(
        "Microphone unavailable. Allow access and try again, or use a demo transcript.",
      );
    }
  };
  return { state, seconds, error, start, transcribe, cancel };
}
