"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { readLocal, writeLocal } from "@/lib/storage/preferences";
export type Theme = "system" | "light" | "dark";
export interface Profile {
  name: string;
  email: string;
  role: string;
  timezone: string;
}
export const defaultProfile: Profile = {
  name: "Elena Rostova",
  email: "elena.rostova@acme.ai",
  role: "Staff Architect",
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
  profile: Profile;
  updateProfile: (changes: Partial<Profile>) => void;
  notice: string;
}
const Context = createContext<WorkspaceState | null>(null);
export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [theme, updateTheme] = useState<Theme>("light");
  const [dark, setDark] = useState(false);
  const [compact, updateCompact] = useState(false);
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
        profile,
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
