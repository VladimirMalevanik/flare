"use client";
import { useI18n } from "@/i18n/provider";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
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
import {
  CAPTURE_PANEL_SIZES,
  clampOrbPosition,
  captureTransformOrigin,
  hoverRectFor,
  placeCapturePanel,
  type CapturePoint,
  type CaptureSize,
} from "./capture-position";
import { useVoiceCapture } from "./use-voice-capture";
import { advanceFunnyShake, beginShake, funnyMessage, moveShake, REQUIRED_SHAKES, type ShakeTracker } from "@/features/funny/funny-state";
import { playFunnySound } from "@/features/funny/funny-sounds";

class CaptureInputError extends Error {}

const ORB_POSITION_KEY = "flare-orb-position-v1";
const MAX_IMPORT_BYTES = 200_000;
export const CAPTURE_TOAST_DISMISS_MS = 4000;
type PointerStart = {
  pointerId: number;
  pointerX: number;
  pointerY: number;
  orbX: number;
  orbY: number;
  moved: boolean;
  ritual: boolean;
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

export function Capture() {
  const { t, locale, message } = useI18n();

  const {
    captureOpen,
    openCapture,
    closeCapture,
    draft,
    setDraft,
    refresh,
    captureOrbSize,
    funnyMode, funnySounds, funnyRitual, setFunnyRitual,
    funnyAudioPaused, setFunnyAudioPaused,
  } = useWorkspace();
  const orbSize =
    captureOrbSize === "small" ? 36 : captureOrbSize === "large" ? 52 : 44;
  const [hovered, setHovered] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const [panelClosing, setPanelClosing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [orbDragging, setOrbDragging] = useState(false);
  const [orbPosition, setOrbPosition] = useState<CapturePoint | null>(null);
  const [viewport, setViewport] = useState<CaptureSize | null>(null);
  const [panelSize, setPanelSize] = useState<(CaptureSize & { preference: typeof captureOrbSize }) | null>(null);
  const island = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const pointerStart = useRef<PointerStart | null>(null);
  const suppressClick = useRef(false);
  const toastTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);
  const voice = useVoiceCapture();
  const voiceIsland = !["idle", "error", "ready"].includes(voice.state);
  const ritualActive = funnyMode && ["armed", "shaken", "thinking"].includes(funnyRitual.phase);
  const shakeTracker = useRef<ShakeTracker | null>(null);
  const [shakeOffset, setShakeOffset] = useState(0);

  useEffect(() => {
    setFunnyAudioPaused(voiceIsland);
    return () => setFunnyAudioPaused(false);
  }, [voiceIsland, voice.state, setFunnyAudioPaused]);

  const shakeBall = () => {
    setFunnyRitual(advanceFunnyShake);
    playFunnySound("shake", funnySounds && !funnyAudioPaused);
  };

  useEffect(() => () => {
    if (closeTimer.current !== null) window.clearTimeout(closeTimer.current);
  }, []);

  useEffect(() => {
    if (!saved) return;
    toastTimer.current = window.setTimeout(() => setSaved(""), CAPTURE_TOAST_DISMISS_MS);
    return () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
      toastTimer.current = null;
    };
  }, [saved]);

  const dismissToast = useCallback(() => {
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = null;
    setSaved("");
  }, []);

  useEffect(() => {
    const savedPosition = readLocal<Partial<CapturePoint> | null>(
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
      const nextViewport = { width: window.innerWidth, height: window.innerHeight };
      setViewport(nextViewport);
      setOrbPosition(clampOrbPosition(
        restoredPosition ?? { x: nextViewport.width / 2, y: orbSize / 2 + 19 },
        orbSize,
        nextViewport,
      ));
    });
    const keepInsideViewport = () => {
      const nextViewport = { width: window.innerWidth, height: window.innerHeight };
      setViewport(nextViewport);
      setOrbPosition((current) =>
        current ? clampOrbPosition(current, orbSize, nextViewport) : current,
      );
    };
    window.addEventListener("resize", keepInsideViewport);
    return () => {
      cancelAnimationFrame(restoreFrame);
      window.removeEventListener("resize", keepInsideViewport);
    };
  }, [orbSize]);

  useLayoutEffect(() => {
    if ((!captureOpen && !voiceIsland) || !panel.current) return;
    const element = panel.current;
    const measure = () => {
      setPanelSize({ width: element.offsetWidth, height: element.offsetHeight, preference: captureOrbSize });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [captureOpen, voiceIsland, captureOrbSize]);

  const close = useCallback(() => {
    if (busy || panelClosing) return;
    setDragging(false);
    setHovered(false);
    setPanelClosing(true);
    closeTimer.current = window.setTimeout(() => {
      voice.cancel();
      closeCapture();
      setPanelClosing(false);
      closeTimer.current = null;
    }, 180);
  }, [busy, closeCapture, panelClosing, voice]);

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
      ritual: ritualActive,
    };
    shakeTracker.current = ritualActive ? beginShake(event.clientX, event.clientY, event.timeStamp) : null;
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const moveOrb = (event: React.PointerEvent<HTMLButtonElement>) => {
    const start = pointerStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    if (start.ritual) {
      if (shakeTracker.current) {
        const next = moveShake(shakeTracker.current, event.clientX, event.clientY, event.timeStamp);
        shakeTracker.current = next.tracker;
        if (next.shake && ritualActive) shakeBall();
      }
      start.moved = true;
      setShakeOffset(Math.max(-24, Math.min(24, event.clientX - start.pointerX)));
      return;
    }
    const distance = Math.hypot(
      event.clientX - start.pointerX,
      event.clientY - start.pointerY,
    );
    if (distance < 5 && !start.moved) return;
    start.moved = true;
    setOrbDragging(true);
    setHovered(false);
    setOrbPosition(
      viewport ? clampOrbPosition({
        x: start.orbX + event.clientX - start.pointerX,
        y: start.orbY + event.clientY - start.pointerY,
      }, orbSize, viewport) : orbPosition,
    );
  };
  const finishOrbDrag = (event: React.PointerEvent<HTMLButtonElement>) => {
    const start = pointerStart.current;
    if (!start || start.pointerId !== event.pointerId) return;
    pointerStart.current = null;
    shakeTracker.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    suppressClick.current = true;
    if (start.ritual) { setShakeOffset(0); return; }
    if (start.moved) {
      if (!viewport) return;
      const next = clampOrbPosition({
        x: start.orbX + event.clientX - start.pointerX,
        y: start.orbY + event.clientY - start.pointerY,
      }, orbSize, viewport);
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
    shakeTracker.current = null;
    setShakeOffset(0);
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
            if (!format) throw new CaptureInputError("Flare can import CSV, TXT, and Markdown files.");
            // File.text() strips a UTF-8 BOM while File.size still counts it.
            // Preserve the transport bytes so the server can validate the byte
            // size, deduplicate the exact upload, then intentionally strip the
            // BOM before parsing and storage.
            const content = new TextDecoder("utf-8", {
              fatal: true,
              ignoreBOM: true,
            }).decode(await file.arrayBuffer());
            if (!content.trim()) throw new CaptureInputError("The import file is empty.");
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
      setError(caught instanceof CaptureInputError ? caught.message : dataErrorMessage(caught, "Capture failed. Try again."));
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
      : hovered && !funnyMode
        ? "hover"
        : "idle";
  const expandedWidth = orbSize + Math.max(76, t("Add context").length * 8) + 12 + 14;
  const hoverPlacement = orbPosition && viewport
    ? hoverRectFor(orbPosition, orbSize, expandedWidth, viewport.width)
    : null;
  const desiredPanelSize = CAPTURE_PANEL_SIZES[captureOrbSize];
  const requestedPanelSize = stage === "voice"
    ? { width: 360, height: 52 }
    : { width: desiredPanelSize.width, height: Math.max(desiredPanelSize.height, panelSize?.preference === captureOrbSize ? panelSize.height : 0) };
  const panelPlacement = orbPosition && viewport && (stage === "capture" || stage === "voice")
    ? placeCapturePanel(orbPosition, orbSize, requestedPanelSize, viewport)
    : null;
  const panelOrigin = panelPlacement && orbPosition
    ? captureTransformOrigin(orbPosition, panelPlacement)
    : null;
  const panelStyle = panelPlacement && panelOrigin
    ? {
        left: panelPlacement.x,
        top: panelPlacement.y,
        width: panelPlacement.width,
        "--capture-panel-min-height": `${Math.min(desiredPanelSize.height, panelPlacement.height)}px`,
        "--capture-textarea-height": `${desiredPanelSize.textareaHeight}px`,
        "--capture-origin-x": `${panelOrigin.x}px`,
        "--capture-origin-y": `${panelOrigin.y}px`,
        "--capture-start-scale-x": `${orbSize / panelPlacement.width}`,
        "--capture-start-scale-y": `${orbSize / panelPlacement.height}`,
      } as CSSProperties
    : undefined;

  return (
    <>
      <div
        ref={island}
        className={`flare-capture orb-size-${captureOrbSize} flare-capture--${stage} flare-capture--expand-${hoverPlacement?.direction ?? "right"} ${dragging ? "is-dragging" : ""} ${orbDragging ? "is-orb-dragging" : ""} ${funnyMode ? "flare-capture--funny" : ""} ${ritualActive ? "flare-capture--ritual" : ""}`}
        data-capture-state={stage}
        style={
          orbPosition
            ? {
                left: orbPosition.x - orbSize / 2,
                top: orbPosition.y - orbSize / 2,
                "--flare-hover-width": `${expandedWidth}px`,
                "--funny-callout-left": `${orbPosition.x - 140}px`,
                "--funny-callout-top": `${orbPosition.y > (viewport?.height ?? 800) - 210 ? orbPosition.y - 170 : orbPosition.y + orbSize / 2 + 16}px`,
              } as CSSProperties
            : undefined
        }
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {stage === "idle" || stage === "hover" ? (
          <button
            className="flare-capture-trigger"
            aria-label={ritualActive ? t("Shake the Magic 8-ball. Drag back and forth, or press Space or Enter four times.") : funnyMode ? t("Magic 8-ball: add context") : t("Add context")}
            aria-haspopup={ritualActive ? undefined : "dialog"}
            aria-describedby={ritualActive ? "funny-ball-instructions" : undefined}
            aria-expanded={captureOpen}
            data-funny-sound={funnyMode ? "off" : undefined}
            onFocus={() => setHovered(true)}
            onBlur={() => setHovered(false)}
            onPointerDown={startOrbDrag}
            onPointerMove={moveOrb}
            onPointerUp={finishOrbDrag}
            onPointerCancel={cancelOrbDrag}
            onLostPointerCapture={cancelOrbDrag}
            onKeyDown={(event) => {
              if (ritualActive && (event.key === " " || event.key === "Enter")) {
                event.preventDefault();
                if (!event.repeat) shakeBall();
              }
            }}
            onClick={() => {
              if (suppressClick.current) {
                suppressClick.current = false;
                return;
              }
              if (!ritualActive) openCapture();
            }}
          >
            <span className={`flare-orb ${funnyMode ? "funny-ball" : ""}`} aria-hidden="true"
              data-phase={funnyRitual.phase} data-shaking={shakeOffset !== 0}
              style={funnyMode ? { "--funny-shake-x": `${shakeOffset}px` } as CSSProperties : undefined}>
              {funnyMode && <><span className="funny-ball-shine" /><span key={ritualActive ? funnyRitual.shakes : 0} className="funny-ball-number">8</span></>}
            </span>
            <span className="flare-capture-label">{t("Add context")}</span>
          </button>
        ) : <span className="flare-capture-anchor" aria-hidden="true" />}
        {funnyMode && !captureOpen && !voiceIsland && funnyRitual.phase !== "idle" && (
          <div className="funny-ball-callout" id="funny-ball-instructions" role="status" aria-live="polite">
            <strong>{funnyMessage(funnyRitual)}</strong>
            {funnyRitual.phase === "armed" && <>
              <span className="funny-ball-hint">{t("Shake instructions")}</span>
              <span className="funny-ball-progress" aria-label={`${Math.min(funnyRitual.shakes, REQUIRED_SHAKES)} of ${REQUIRED_SHAKES} shakes`}>
                {Array.from({ length: REQUIRED_SHAKES }, (_, index) => <i key={index} data-complete={index < funnyRitual.shakes} />)}
              </span>
            </>}
            {["complete", "empty", "error"].includes(funnyRitual.phase) && <button className="text-button"
              onClick={() => setFunnyRitual((value) => ({ ...value, phase: "idle", shakes: 0 }))}>{t("Got it")}</button>}
          </div>
        )}
        {voiceIsland ? (
          <div
            ref={panel as React.RefObject<HTMLDivElement>}
            className="flare-recording-island"
            role="status"
            aria-live="polite"
            style={panelStyle}
          >
            {voice.state === "recording" ? (
              <>
                <div className="voice-waveform" aria-label={t("Recording waveform")}>
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
                  aria-label={t("Stop recording")}
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
                  ? t("Allow microphone…")
                  : t("Finishing recording…")}
              </span>
            )}
            <button className="icon-button" aria-label={t("Cancel recording")} onClick={voice.cancel}>
              <Icon name="close" />
            </button>
          </div>
        ) : captureOpen ? (
          <section
            ref={panel}
            className={`flare-capture-panel ${panelClosing ? "is-closing" : ""}`}
            role="dialog"
            aria-label={t("Capture")}
            style={panelStyle}
          >
            <header className="capture-panel-header">
              <strong>{t("Add context")}</strong>
            </header>
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
                aria-label={t("Capture content")}
                placeholder={t("Type a note or import a text file…")}
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
                  <span>{file.name} · {new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(file.size / 1024)} KB</span>
                  <button
                    className="icon-button"
                    aria-label={t("Remove attachment")}
                    disabled={busy}
                    onClick={() => setFile(null)}
                  >
                    <Icon name="close" />
                  </button>
                </div>
              )}
              {file && (
                <p className="capture-hint">
                  {importFormatForFile(file)?.toUpperCase()} {" "}{t("import · text is saved to this workspace")}</p>
              )}
            </div>
            {voice.recording && (
              <div className="capture-hint voice-ready" role="status">
                <p>
                  {t("Voice transcription currently uses English. Your recording will be sent to our transcription provider only when you choose Transcribe & save. Flare stores the transcript, not the source audio.")}</p>
                <div className="form-actions">
                  <button
                    className="button primary"
                    disabled={busy}
                    onClick={() => void submitVoice()}
                  >
                    {busy ? t("Transcribing…") : t("Transcribe & save")}
                  </button>
                  <button className="text-button" disabled={busy} onClick={voice.cancel}>
                    {t("Discard recording")}</button>
                </div>
              </div>
            )}
            {voice.error && (
              <div className="capture-error" role="alert">
                <p>{message(voice.error)}</p>
              </div>
            )}
            {error && (
              <p className="capture-error" role="alert">
                {message(error)}
              </p>
            )}
            <footer className="capture-actions">
              <button
                className="icon-button"
                aria-label={t("Add file")}
                disabled={busy || voiceIsland || !!voice.recording}
                onClick={() => fileInput.current?.click()}
              >
                <Icon name="file" />
              </button>
              <button
                className="icon-button"
                aria-label={t("Record a voice memo")}
                title={t("Record a voice memo (English transcription)")}
                data-funny-sound="off"
                disabled={busy || voiceIsland || !!voice.recording || !!file || !!draft.trim()}
                onClick={() => {
                  setError("");
                  setFunnyAudioPaused(true);
                  void dataProvider.trackEvent({ eventType: "capture_voice_started", targetType: "capture" });
                  void voice.start();
                }}
              >
                <Icon name="audio" />
              </button>
              <span className="capture-drop-hint">
                {dragging ? t("Drop CSV, TXT, or Markdown") : t("Import CSV, TXT, or Markdown")}
              </span>
              <button
                className="button primary"
                disabled={busy || !!voice.recording || (!draft.trim() && !file)}
                onClick={() => void submit()}
              >
                {busy ? t("Saving…") : file ? t("Import") : t("Capture")}
                <span className="shortcut">⌘↵</span>
              </button>
              <button
                className="icon-button capture-close"
                aria-label={t("Close capture")}
                disabled={busy}
                onClick={close}
              >
                <Icon name="close" />
              </button>
            </footer>
          </section>
        ) : null}
      </div>
      <input
        ref={fileInput}
        type="file"
        accept=".csv,.txt,.md,.markdown,text/csv,text/plain,text/markdown"
        className="sr-only"
        tabIndex={-1}
        aria-label={t("Capture file")}
        onChange={(event) => {
          attach(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      {saved && (
        <div className="toast capture-toast" role="status">
          <span>{t("Captured in Vault")}</span>
          <Link href={`/vault?item=${saved}`} onClick={dismissToast}>
            {t("View item →")}</Link>
          <button
            className="icon-button"
            aria-label={t("Dismiss capture confirmation")}
            onClick={dismissToast}
          >
            <Icon name="close" />
          </button>
        </div>
      )}
    </>
  );
}
