"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "@/components/icons";
import { useWorkspace } from "@/components/workspace-context";
import {
  dataErrorMessage,
  dataProvider,
  type CreateItemInput,
  type ImportFormat,
} from "@/lib/data";
import { readLocal, writeLocal } from "@/lib/storage/preferences";
import { transcribeVoice } from "@/lib/voice";
import { useVoiceCapture } from "./use-voice-capture";

const ORB_POSITION_KEY = "flare-orb-position-v1";
const ORB_EDGE_PADDING = 12;
const PANEL_EDGE_MARGIN = 16;
const MAX_IMPORT_BYTES = 200_000;
type OrbPosition = { x: number; y: number };
type PointerStart = {
  pointerId: number;
  pointerX: number;
  pointerY: number;
  orbX: number;
  orbY: number;
  moved: boolean;
};

function importFormatForFile(file: File): ImportFormat | null {
  const name = file.name.trim().toLowerCase();
  if (name.endsWith(".csv")) return "csv";
  if (name.endsWith(".txt")) return "txt";
  if (name.endsWith(".md") || name.endsWith(".markdown")) return "md";
  return null;
}

function elapsed(seconds: number) {
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}

function clampOrbPosition(position: OrbPosition, orbSize: number): OrbPosition {
  const edgeMargin = orbSize / 2 + ORB_EDGE_PADDING;
  return {
    x: Math.min(
      Math.max(edgeMargin, position.x),
      window.innerWidth - edgeMargin,
    ),
    y: Math.min(
      Math.max(edgeMargin, position.y),
      window.innerHeight - edgeMargin,
    ),
  };
}

function clampPanelAxis(value: number, size: number, viewport: number) {
  if (size + PANEL_EDGE_MARGIN * 2 >= viewport) return viewport / 2;
  return Math.min(
    Math.max(value, size / 2 + PANEL_EDGE_MARGIN),
    viewport - size / 2 - PANEL_EDGE_MARGIN,
  );
}

function panelPositionFor(
  position: OrbPosition,
  stage: "capture" | "voice",
): OrbPosition {
  const width = Math.min(
    stage === "voice" ? 360 : 500,
    window.innerWidth - PANEL_EDGE_MARGIN * 2,
  );
  const height = stage === "voice" ? 52 : 360;
  return {
    x: clampPanelAxis(position.x, width, window.innerWidth),
    y: clampPanelAxis(position.y, height, window.innerHeight),
  };
}

export function Capture() {
  const {
    captureOpen,
    openCapture,
    closeCapture,
    draft,
    setDraft,
    refresh,
    captureOrbSize,
  } = useWorkspace();
  const orbSize =
    captureOrbSize === "small" ? 36 : captureOrbSize === "large" ? 52 : 44;
  const [hovered, setHovered] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [dragging, setDragging] = useState(false);
  const [orbDragging, setOrbDragging] = useState(false);
  const [orbPosition, setOrbPosition] = useState<OrbPosition | null>(null);
  const island = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const pointerStart = useRef<PointerStart | null>(null);
  const suppressClick = useRef(false);
  const voice = useVoiceCapture();
  const voiceIsland = !["idle", "error", "ready"].includes(voice.state);

  useEffect(() => {
    const savedPosition = readLocal<Partial<OrbPosition> | null>(
      ORB_POSITION_KEY,
      null,
    );
    const restoredPosition =
      savedPosition &&
      typeof savedPosition.x === "number" &&
      typeof savedPosition.y === "number"
        ? { x: savedPosition.x, y: savedPosition.y }
        : null;
    const restoreFrame = requestAnimationFrame(() => {
      if (restoredPosition)
        setOrbPosition(clampOrbPosition(restoredPosition, orbSize));
    });
    const keepInsideViewport = () => {
      setOrbPosition((current) =>
        current ? clampOrbPosition(current, orbSize) : current,
      );
    };
    window.addEventListener("resize", keepInsideViewport);
    return () => {
      cancelAnimationFrame(restoreFrame);
      window.removeEventListener("resize", keepInsideViewport);
    };
  }, [orbSize]);

  const close = useCallback(() => {
    if (busy) return;
    voice.cancel();
    setDragging(false);
    setHovered(false);
    closeCapture();
  }, [busy, closeCapture, voice]);

  useEffect(() => {
    if (!captureOpen) return;
    void dataProvider.trackEvent({
      eventType: "capture_started",
      targetType: "capture",
    });
  }, [captureOpen]);

  const attach = (next: File | undefined) => {
    if (!next || voiceIsland || voice.recording || busy) return;
    const format = importFormatForFile(next);
    if (!format) {
      setError("Flare can import CSV, TXT, and Markdown files.");
      return;
    }
    if (next.size > MAX_IMPORT_BYTES) {
      setError("This import is too large. Choose a file up to 200 KB.");
      return;
    }
    setError("");
    setFile(next);
    void dataProvider.trackEvent({
      eventType: "capture_file_attached",
      targetType: "import",
      metadata: { format, fileSize: next.size },
    });
  };

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        openCapture();
      }
      if (event.key === "Escape" && captureOpen) close();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [captureOpen, close, openCapture]);

  useEffect(() => {
    if (!captureOpen) return;
    const outside = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !island.current?.contains(event.target)
      )
        close();
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [captureOpen, close]);

  const startOrbDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0 && event.pointerType !== "touch") return;
    const rect = island.current?.getBoundingClientRect();
    if (!rect) return;
    pointerStart.current = {
      pointerId: event.pointerId,
      pointerX: event.clientX,
      pointerY: event.clientY,
      orbX: rect.left + rect.width / 2,
      orbY: rect.top + rect.height / 2,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveOrb = (event: React.PointerEvent<HTMLButtonElement>) => {
    const start = pointerStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    const distance = Math.hypot(
      event.clientX - start.pointerX,
      event.clientY - start.pointerY,
    );
    if (distance < 5 && !start.moved) return;
    start.moved = true;
    setOrbDragging(true);
    setHovered(false);
    setOrbPosition(
      clampOrbPosition({
        x: start.orbX + event.clientX - start.pointerX,
        y: start.orbY + event.clientY - start.pointerY,
      }, orbSize),
    );
  };
  const finishOrbDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    const start = pointerStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    pointerStart.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    suppressClick.current = true;
    if (start.moved) {
      const next = clampOrbPosition({
        x: start.orbX + event.clientX - start.pointerX,
        y: start.orbY + event.clientY - start.pointerY,
      }, orbSize);
      setOrbPosition(next);
      setOrbDragging(false);
      try {
        writeLocal(ORB_POSITION_KEY, next);
      } catch {
        // Position is still useful for the current visit.
      }
      return;
    }
    openCapture();
  };
  const cancelOrbDrag = () => {
    pointerStart.current = null;
    setOrbDragging(false);
  };

  const submit = async () => {
    if (busy || voice.recording || voiceIsland || (!draft.trim() && !file)) return;
    setBusy(true);
    setError("");
    try {
      const item = file
        ? await (async () => {
            const format = importFormatForFile(file);
            if (!format) throw new Error("Flare can import CSV, TXT, and Markdown files.");
            // File.text() strips a UTF-8 BOM while File.size still counts it.
            // Preserve the transport bytes so the server can validate the byte
            // size, deduplicate the exact upload, then intentionally strip the
            // BOM before parsing and storage.
            const content = new TextDecoder("utf-8", {
              fatal: true,
              ignoreBOM: true,
            }).decode(await file.arrayBuffer());
            if (!content.trim()) throw new Error("The import file is empty.");
            const imported = await dataProvider.importTextFile({
              format,
              fileName: file.name,
              fileType: file.type || undefined,
              fileSize: file.size,
              content,
            });
            return imported.item;
          })()
        : await (async () => {
            const content = draft.trim();
            const input: CreateItemInput = {
              type: "note",
              title: content.split("\n")[0].slice(0, 100),
              content,
            };
            return dataProvider.createItem(input);
          })();
      refresh();
      setSaved(item.id);
      setDraft("");
      setFile(null);
      void dataProvider.trackEvent({
        eventType: "capture_submitted",
        targetType: "item",
        targetId: item.id,
        metadata: { sourceType: file ? "file" : "note" },
      });
      closeCapture();
    } catch (caught) {
      setError(dataErrorMessage(caught, "Capture failed. Try again."));
    } finally {
      setBusy(false);
    }
  };

  const submitVoice = async () => {
    if (busy || voice.state !== "ready" || !voice.recording) return;
    setBusy(true);
    setError("");
    try {
      const item = await transcribeVoice(voice.recording);
      refresh();
      setSaved(item.id);
      setDraft("");
      setFile(null);
      void dataProvider.trackEvent({
        eventType: "capture_submitted",
        targetType: "item",
        targetId: item.id,
        metadata: { sourceType: "audio" },
      });
      voice.cancel();
      closeCapture();
    } catch (caught) {
      setError(dataErrorMessage(caught, "Voice transcription failed. Try again."));
    } finally {
      setBusy(false);
    }
  };

  const stage = voiceIsland
    ? "voice"
    : captureOpen
      ? "capture"
      : hovered
        ? "hover"
        : "idle";
  const displayPosition =
    orbPosition && (stage === "capture" || stage === "voice")
      ? panelPositionFor(orbPosition, stage)
      : orbPosition;

  return (
    <>
      <div
        ref={island}
        className={`flare-capture orb-size-${captureOrbSize} flare-capture--${stage} ${dragging ? "is-dragging" : ""} ${orbDragging ? "is-orb-dragging" : ""}`}
        data-capture-state={stage}
        style={
          displayPosition
            ? {
                left: displayPosition.x,
                top: displayPosition.y,
                transform: "translate(-50%, -50%)",
              }
            : undefined
        }
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {stage === "idle" || stage === "hover" ? (
          <button
            className="flare-capture-trigger"
            aria-label="Add context"
            aria-haspopup="dialog"
            aria-expanded={captureOpen}
            onFocus={() => setHovered(true)}
            onBlur={() => setHovered(false)}
            onPointerDown={startOrbDrag}
            onPointerMove={moveOrb}
            onPointerUp={finishOrbDrag}
            onPointerCancel={cancelOrbDrag}
            onClick={() => {
              if (suppressClick.current) {
                suppressClick.current = false;
                return;
              }
              openCapture();
            }}
          >
            <span className="flare-orb" aria-hidden="true" />
            <span className="flare-capture-label">Add context</span>
          </button>
        ) : voiceIsland ? (
          <div
            className="flare-recording-island"
            role="status"
            aria-live="polite"
          >
            <span className="flare-orb" aria-hidden="true" />
            {voice.state === "recording" ? (
              <>
                <div className="voice-waveform" aria-label="Recording waveform">
                  {Array.from({ length: 18 }, (_, index) => (
                    <i
                      key={index}
                      style={{
                        animationDelay: `${index * -0.08}s`,
                        height: `${8 + ((index * 7) % 17)}px`,
                      }}
                    />
                  ))}
                </div>
                <span className="voice-timer">{elapsed(voice.seconds)}</span>
                <button
                  className="voice-stop"
                  aria-label="Stop recording"
                  onClick={() => {
                    void dataProvider.trackEvent({ eventType: "capture_voice_stopped", targetType: "capture" });
                    voice.stop();
                  }}
                >
                  <span />
                </button>
              </>
            ) : (
              <span className="recording-status">
                {voice.state === "requesting"
                  ? "Allow microphone…"
                  : "Finishing recording…"}
              </span>
            )}
            <button className="icon-button" aria-label="Cancel recording" onClick={voice.cancel}>
              <Icon name="close" />
            </button>
          </div>
        ) : (
          <section
            className="flare-capture-panel"
            role="dialog"
            aria-label="Capture"
          >
            <div
              className="capture-dropzone"
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                attach(event.dataTransfer.files[0]);
              }}
            >
              <textarea
                autoFocus
                aria-label="Capture content"
                placeholder="Type a note or import a text file…"
                rows={3}
                value={draft}
                disabled={busy || !!voice.recording}
                onChange={(event) => setDraft(event.target.value)}
                onPaste={(event) => {
                  const pastedFile = event.clipboardData.files[0];
                  if (pastedFile) {
                    event.preventDefault();
                    attach(pastedFile);
                  }
                }}
                onKeyDown={(event) => {
                  if (
                    (event.metaKey || event.ctrlKey) &&
                    event.key === "Enter"
                  ) {
                    event.preventDefault();
                    void submit();
                  }
                }}
              />
              {file && (
                <div className="attachment">
                  <Icon name="file" />
                  <span>{file.name} · {(file.size / 1024).toFixed(1)} KB</span>
                  <button
                    className="icon-button"
                    aria-label="Remove attachment"
                    disabled={busy}
                    onClick={() => setFile(null)}
                  >
                    <Icon name="close" />
                  </button>
                </div>
              )}
              {file && (
                <p className="capture-hint">
                  {importFormatForFile(file)?.toUpperCase()} import · text is saved to this workspace
                </p>
              )}
            </div>
            {voice.recording && (
              <div className="capture-hint voice-ready" role="status">
                <p>
                  Voice transcription currently uses English. Your recording will be sent to our transcription provider only when you choose Transcribe &amp; save. Flare stores the transcript, not the source audio.
                </p>
                <div className="form-actions">
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => void submitVoice()}
                  >
                    {busy ? "Transcribing…" : "Transcribe & save"}
                  </button>
                  <button className="text-button" disabled={busy} onClick={voice.cancel}>
                    Discard recording
                  </button>
                </div>
              </div>
            )}
            {voice.error && (
              <div className="capture-error" role="alert">
                <p>{voice.error}</p>
              </div>
            )}
            {error && (
              <p className="capture-error" role="alert">
                {error}
              </p>
            )}
            <footer className="capture-actions">
              <button
                className="icon-button"
                aria-label="Add file"
                disabled={busy || voiceIsland || !!voice.recording}
                onClick={() => fileInput.current?.click()}
              >
                <Icon name="file" />
              </button>
              <button
                className="icon-button"
                aria-label="Record a voice memo"
                title="Record a voice memo (English transcription)"
                disabled={busy || voiceIsland || !!voice.recording || !!file || !!draft.trim()}
                onClick={() => {
                  setError("");
                  void dataProvider.trackEvent({ eventType: "capture_voice_started", targetType: "capture" });
                  void voice.start();
                }}
              >
                <Icon name="audio" />
              </button>
              <span className="capture-drop-hint">
                {dragging ? "Drop CSV, TXT, or Markdown" : "Import CSV, TXT, or Markdown"}
              </span>
              <button
                className="button primary"
                disabled={busy || !!voice.recording || (!draft.trim() && !file)}
                onClick={() => void submit()}
              >
                {busy ? "Saving…" : file ? "Import" : "Capture"}
                <span className="shortcut">⌘↵</span>
              </button>
              <button
                className="icon-button capture-close"
                aria-label="Close capture"
                disabled={busy}
                onClick={close}
              >
                <Icon name="close" />
              </button>
            </footer>
          </section>
        )}
      </div>
      <input
        ref={fileInput}
        type="file"
        accept=".csv,.txt,.md,.markdown,text/csv,text/plain,text/markdown"
        className="sr-only"
        tabIndex={-1}
        aria-label="Capture file"
        onChange={(event) => {
          attach(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      {saved && (
        <div className="toast" role="status">
          Captured in Vault{" "}
          <Link href={`/vault?item=${saved}`} onClick={() => setSaved("")}>
            View item →
          </Link>
          <button
            className="icon-button"
            aria-label="Dismiss capture confirmation"
            onClick={() => setSaved("")}
          >
            <Icon name="close" />
          </button>
        </div>
      )}
    </>
  );
}
