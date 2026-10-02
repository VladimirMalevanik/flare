// Small synthesized sounds avoid downloads and stay within the user's audio gesture.
export type FunnySound = "click" | "shake" | "success" | "empty" | "error" | "enable";

type SoundNote = { frequency: number; end?: number; offset: number; duration: number };
const melodies: Record<FunnySound, SoundNote[]> = {
  click: [{ frequency: 520, end: 760, offset: 0, duration: 0.055 }],
  shake: [{ frequency: 160, end: 420, offset: 0, duration: 0.075 }],
  success: [
    { frequency: 523, offset: 0, duration: 0.11 },
    { frequency: 659, offset: 0.1, duration: 0.11 },
    { frequency: 784, offset: 0.2, duration: 0.15 },
  ],
  empty: [
    { frequency: 420, end: 360, offset: 0, duration: 0.1 },
    { frequency: 300, offset: 0.11, duration: 0.12 },
  ],
  error: [{ frequency: 190, end: 120, offset: 0, duration: 0.17 }],
  enable: [
    { frequency: 440, end: 660, offset: 0, duration: 0.09 },
    { frequency: 880, offset: 0.09, duration: 0.12 },
  ],
};

let audioContext: AudioContext | null = null;
const activeOscillators = new Set<OscillatorNode>();
let ownedSpeech: SpeechSynthesisUtterance | null = null;
let soundGeneration = 0;
let lastPlayedAt = 0;

export function playFunnySound(kind: FunnySound, enabled: boolean): void {
  if (!enabled || typeof window === "undefined" || document.hidden) return;
  const now = performance.now();
  if (now - lastPlayedAt < 55) return;
  lastPlayedAt = now;
  try {
    const AudioConstructor = window.AudioContext ?? (window as Window & {
      webkitAudioContext?: typeof AudioContext;
    }).webkitAudioContext;
    if (!AudioConstructor) return;
    if (!audioContext || audioContext.state === "closed") audioContext = new AudioConstructor();
    const context = audioContext;
    const generation = soundGeneration;
    const play = () => {
      if (generation !== soundGeneration || context.state !== "running") return;
      const notes = melodies[kind];
      if (activeOscillators.size + notes.length > 6) return;
      for (const note of notes) {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        const start = context.currentTime + note.offset;
        oscillator.type = "sine";
        oscillator.frequency.setValueAtTime(note.frequency, start);
        if (note.end) oscillator.frequency.exponentialRampToValueAtTime(note.end, start + note.duration);
        gain.gain.setValueAtTime(0, start);
        gain.gain.linearRampToValueAtTime(0.035, start + 0.008);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + note.duration);
        oscillator.connect(gain);
        gain.connect(context.destination);
        activeOscillators.add(oscillator);
        oscillator.onended = () => {
          activeOscillators.delete(oscillator);
          oscillator.disconnect();
          gain.disconnect();
        };
        oscillator.start(start);
        oscillator.stop(start + note.duration + 0.01);
      }
    };
    if (context.state === "suspended") void context.resume().then(play).catch(() => {});
    else play();
  } catch {
    // Audio support or browser policy must never interrupt a real action.
  }
}

export function speakFunnyLine(text: string, enabled: boolean): void {
  if (!enabled || typeof window === "undefined" || document.hidden) return;
  try {
    const speech = window.speechSynthesis;
    if (!speech || speech.speaking || speech.pending) return;
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 140));
    utterance.lang = "en-US";
    utterance.rate = 1.05;
    utterance.volume = 0.55;
    ownedSpeech = utterance;
    const clear = () => { if (ownedSpeech === utterance) ownedSpeech = null; };
    utterance.onend = clear;
    utterance.onerror = clear;
    speech.speak(utterance);
  } catch {
    ownedSpeech = null;
  }
}

export function stopFunnySounds(): void {
  soundGeneration += 1;
  for (const oscillator of activeOscillators) {
    try { oscillator.stop(); } catch {}
  }
  activeOscillators.clear();
  if (audioContext) {
    const context = audioContext;
    audioContext = null;
    void context.close().catch(() => {});
  }
  if (ownedSpeech && typeof window !== "undefined") {
    window.speechSynthesis?.cancel();
    ownedSpeech = null;
  }
}
