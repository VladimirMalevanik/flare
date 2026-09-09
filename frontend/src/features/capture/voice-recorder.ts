export type Recording = { blob: Blob; mimeType: string };
export type VoiceState = "idle" | "requesting" | "recording" | "stopping" | "ready" | "error";
export type VoiceSnapshot = { state: VoiceState; recording: Recording | null; error: string };

// Transport-free controller, also exercised with fake browser media in Node tests.
export class VoiceRecorder {
  private generation = 0;
  private media: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private timeout: ReturnType<typeof setTimeout> | null = null;
  private snapshot: VoiceSnapshot = { state: "idle", recording: null, error: "" };
  constructor(private publish: (snapshot: VoiceSnapshot) => void) {}

  private update(snapshot: VoiceSnapshot) {
    this.snapshot = snapshot;
    this.publish(snapshot);
  }
  private release() {
    if (this.timeout) clearTimeout(this.timeout);
    this.timeout = null;
    const recorder = this.recorder;
    this.recorder = null;
    if (recorder) {
      recorder.ondataavailable = null;
      recorder.onstop = null;
      recorder.onerror = null;
      try {
        if (recorder.state !== "inactive") recorder.stop();
      } catch {
        // Track cleanup must still run when a browser recorder has already failed.
      }
    }
    this.media?.getTracks().forEach((track) => track.stop());
    this.media = null;
  }
  cancel = () => {
    this.generation++;
    this.release();
    this.update({ state: "idle", recording: null, error: "" });
  };
  dispose = () => {
    this.generation++;
    this.release();
    this.snapshot = { state: "idle", recording: null, error: "" };
  };
  private fail(message: string) {
    this.generation++;
    this.release();
    this.update({ state: "error", recording: null, error: message });
  }
  stop = () => {
    if (this.snapshot.state !== "recording") return;
    this.update({ state: "stopping", recording: null, error: "" });
    if (this.timeout) clearTimeout(this.timeout);
    this.timeout = null;
    try {
      this.recorder?.stop();
      this.media?.getTracks().forEach((track) => track.stop());
      this.media = null;
    } catch {
      this.fail("Recording interrupted. Try again.");
    }
  };
  start = async () => {
    if (!["idle", "error"].includes(this.snapshot.state)) return;
    const id = ++this.generation;
    this.update({ state: "requesting", recording: null, error: "" });
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") throw new Error();
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]
        .find((mime) => MediaRecorder.isTypeSupported(mime));
      if (!mimeType) throw new Error();
      const media = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (id !== this.generation) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      this.media = media;
      const recorder = new MediaRecorder(media, { mimeType });
      this.recorder = recorder;
      const chunks: Blob[] = [];
      let size = 0;
      recorder.ondataavailable = (event) => {
        if (id !== this.generation || !event.data.size) return;
        size += event.data.size;
        if (size > 10 * 1024 * 1024) {
          this.fail("Recording is too large. Try a shorter recording.");
          return;
        }
        chunks.push(event.data);
      };
      recorder.onerror = () => {
        if (id === this.generation) this.fail("Recording interrupted. Try again.");
      };
      recorder.onstop = () => {
        if (id !== this.generation) return;
        const blob = new Blob(chunks, { type: recorder.mimeType || mimeType });
        this.release();
        if (!blob.size) {
          this.fail("No audio recorded. Try again.");
          return;
        }
        this.update({ state: "ready", recording: { blob, mimeType: blob.type }, error: "" });
      };
      recorder.start(1000);
      this.update({ state: "recording", recording: null, error: "" });
      this.timeout = setTimeout(this.stop, 300_000);
    } catch {
      if (id === this.generation) this.fail("Microphone unavailable. Allow access and try again.");
    }
  };
}
