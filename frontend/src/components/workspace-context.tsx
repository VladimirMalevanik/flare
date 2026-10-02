"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import { useSession } from "./auth-session";
import { readLocal, writeLocal } from "@/lib/storage/preferences";
import { INITIAL_FUNNY_RITUAL, type FunnyRitualState } from "@/features/funny/funny-state";
import { stopFunnySounds } from "@/features/funny/funny-sounds";
export type Theme = "system" | "light" | "dark";
export type CaptureOrbSize = "small" | "medium" | "large";
export interface Profile {
  name: string;
  email: string;
  role: string;
  timezone: string;
}
export const defaultProfile: Profile = {
  name: "Elena Rostova",
  email: "elena@northstar.app",
  role: "Founder",
  timezone: "Europe/Moscow",
};
interface WorkspaceState {
  theme: Theme;
  dark: boolean;
  setTheme: (theme: Theme) => void;
  captureOpen: boolean;
  openCapture: (draft?: string) => void;
  closeCapture: () => void;
  draft: string;
  setDraft: (draft: string) => void;
  revision: number;
  refresh: () => void;
  compact: boolean;
  setCompact: (value: boolean) => void;
  captureOrbSize: CaptureOrbSize;
  setCaptureOrbSize: (value: CaptureOrbSize) => void;
  funnyMode: boolean;
  setFunnyMode: (value: boolean) => void;
  funnySounds: boolean;
  setFunnySounds: (value: boolean) => void;
  funnyRitual: FunnyRitualState;
  setFunnyRitual: Dispatch<SetStateAction<FunnyRitualState>>;
  funnyAudioPaused: boolean;
  setFunnyAudioPaused: (value: boolean) => void;
  profile: Profile;
  updateProfile: (changes: Partial<Profile>) => void;
  notice: string;
}
const Context = createContext<WorkspaceState | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const session = useSession();
  const [theme, updateTheme] = useState<Theme>("light");
  const [dark, setDark] = useState(false);
  const [compact, updateCompact] = useState(false);
  const [captureOrbSize, updateCaptureOrbSize] =
    useState<CaptureOrbSize>("medium");
  const [funnyMode, updateFunnyMode] = useState(false);
  const [funnySounds, updateFunnySounds] = useState(true);
  const [funnyRitual, setFunnyRitual] = useState(INITIAL_FUNNY_RITUAL);
  const [funnyAudioPaused, updateFunnyAudioPaused] = useState(false);
  const [captureOpen, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [revision, setRevision] = useState(0);
  const [notice, setNotice] = useState("");
  const [profile, setProfile] = useState<Profile>(defaultProfile);
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const sync = () => {
      const stored = readLocal<Theme>("flare-theme", "light");
      const selected = ["light", "dark", "system"].includes(stored)
        ? stored
        : "light";
      updateTheme(selected);
      setDark(selected === "dark" || (selected === "system" && media.matches));
      updateCompact(readLocal<boolean>("flare-compact", false) === true);
      const storedFunnyMode = readLocal<boolean>("flare-funny-mode-v1", false) === true;
      const storedFunnySounds = readLocal<boolean>("flare-funny-sounds-v1", true) !== false;
      updateFunnyMode(storedFunnyMode);
      updateFunnySounds(storedFunnySounds);
      if (!storedFunnyMode) {
        setFunnyRitual((current) => ({ ...INITIAL_FUNNY_RITUAL, requestId: current.requestId }));
      }
      if (!storedFunnyMode || !storedFunnySounds) stopFunnySounds();
      const storedOrbSize = readLocal<CaptureOrbSize>(
        "flare-capture-orb-size-v1",
        "medium",
      );
      updateCaptureOrbSize(
        ["small", "medium", "large"].includes(storedOrbSize)
          ? storedOrbSize
          : "medium",
      );
      const legacy = readLocal<Partial<Profile>>("flare-settings-v1", {});
      const storedProfile = readLocal<Partial<Profile>>(
        "flare-profile-v1",
        {},
      );
      setProfile({ ...defaultProfile, ...legacy, ...storedProfile });
    };
    sync();
    media.addEventListener("change", sync);
    window.addEventListener("storage", sync);
    return () => {
      media.removeEventListener("change", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document.documentElement.dataset.compact = String(compact);
  }, [dark, compact]);
  useEffect(() => {
    document.documentElement.dataset.funnyMode = String(funnyMode);
    return () => {
      delete document.documentElement.dataset.funnyMode;
    };
  }, [funnyMode]);
  const setFunnyMode = (value: boolean) => {
    updateFunnyMode(value);
    if (!value) {
      stopFunnySounds();
      setFunnyRitual((current) => ({ ...INITIAL_FUNNY_RITUAL, requestId: current.requestId }));
    }
    try {
      writeLocal("flare-funny-mode-v1", value);
    } catch {
      setNotice("Funny mode changed for this visit. Browser storage is unavailable.");
    }
  };
  const setFunnySounds = (value: boolean) => {
    updateFunnySounds(value);
    if (!value) stopFunnySounds();
    try {
      writeLocal("flare-funny-sounds-v1", value);
    } catch {
      setNotice("Funny sounds changed for this visit. Browser storage is unavailable.");
    }
  };
  const setFunnyAudioPaused = useCallback((value: boolean) => {
    if (value) stopFunnySounds();
    updateFunnyAudioPaused(value);
  }, []);
  const setTheme = (value: Theme) => {
    updateTheme(value);
    setDark(
      value === "dark" ||
        (value === "system" &&
          matchMedia("(prefers-color-scheme: dark)").matches),
    );
    try {
      writeLocal("flare-theme", value);
    } catch {
      setNotice(
        "Theme changed for this visit. Browser storage is unavailable.",
      );
    }
  };
  const setCompact = (value: boolean) => {
    updateCompact(value);
    try {
      writeLocal("flare-compact", value);
    } catch {
      setNotice(
        "Density changed for this visit. Browser storage is unavailable.",
      );
    }
  };
  const setCaptureOrbSize = (value: CaptureOrbSize) => {
    updateCaptureOrbSize(value);
    try {
      writeLocal("flare-capture-orb-size-v1", value);
    } catch {
      setNotice("Orb size changed for this visit. Browser storage is unavailable.");
    }
  };
  const updateProfile = (changes: Partial<Profile>) => {
    const next = { ...profile, ...changes };
    setProfile(next);
    try {
      writeLocal("flare-profile-v1", next);
    } catch {
      setNotice(
        "Profile changed for this visit. Browser storage is unavailable.",
      );
    }
  };
  return (
    <Context.Provider
      value={{
        theme,
        dark,
        setTheme,
        compact,
        setCompact,
        captureOrbSize,
        setCaptureOrbSize,
        funnyMode,
        setFunnyMode,
        funnySounds,
        setFunnySounds,
        funnyRitual,
        setFunnyRitual,
        funnyAudioPaused,
        setFunnyAudioPaused,
        profile: session ? { ...profile, name: session.user.name, email: session.user.email, role: session.workspace.role } : profile,
        updateProfile,
        captureOpen,
        openCapture: (text) => {
          if (text !== undefined) setDraft(text);
          setOpen(true);
        },
        closeCapture: () => setOpen(false),
        draft,
        setDraft,
        revision,
        refresh: () => setRevision((n) => n + 1),
        notice,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useWorkspace() {
  const value = useContext(Context);
  if (!value) throw new Error("WorkspaceProvider missing");
  return value;
}
