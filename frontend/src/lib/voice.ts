import { apiBaseUrl } from "@/lib/auth/session";
import type { Recording } from "@/features/capture/voice-recorder";

export async function transcribeVoice(recording: Recording): Promise<{ id: string }> {
  const response = await fetch(`${apiBaseUrl}/voice/transcribe`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: {
      "Content-Type": recording.mimeType,
    },
    body: recording.blob,
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.location.replace("/login");
  }
  if (!response.ok) {
    let message = "Voice transcription failed. Please try again.";
    try {
      const payload: unknown = await response.json();
      if (typeof payload === "object" && payload !== null) {
        const detail = (payload as { detail?: unknown }).detail;
        if (typeof detail === "string") message = detail;
      }
    } catch {
      // Keep the stable client-safe fallback.
    }
    throw new Error(message);
  }
  const payload: unknown = await response.json();
  if (
    typeof payload !== "object" ||
    payload === null ||
    typeof (payload as { id?: unknown }).id !== "string"
  ) {
    throw new Error("The server returned an invalid voice item.");
  }
  return { id: (payload as { id: string }).id };
}
