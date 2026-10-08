"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Icon } from "./icons";
import { WorkspaceProvider, useWorkspace } from "./workspace-context";
import { Capture } from "@/features/capture/capture";
import { FunnyEffects } from "@/features/funny/funny-effects";
import { dataProvider } from "@/lib/data";
import { Dialog } from "./dialog";
import { BrandMark } from "./brand-mark";
import { useI18n } from "@/i18n/provider";
const navigation = [
  { href: "/insights", label: "flares", icon: "insights" },
  { href: "/vault", label: "vault", icon: "vault" },
  { href: "/sources", label: "sources", icon: "sources" },
  { href: "/settings", label: "settings", icon: "settings" },
] as const;
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <WorkspaceProvider>
      <Shell>{children}</Shell>
    </WorkspaceProvider>
  );
}
function Shell({ children }: { children: ReactNode }) {
  const { t, message } = useI18n();
  const pathname = usePathname();
  const [drawer, setDrawer] = useState(false);
  const settingsPresses = useRef(0);
  const { dark, setTheme, openCapture, revision, notice, profile, funnyMode, setFunnyMode } =
    useWorkspace();
  const initials =
    profile.name
      .split(" ")
      .map((part) => part[0])
      .filter(Boolean)
      .slice(0, 2)
      .join("") || "F";
  const [counts, setCounts] = useState([0, 0, 0]);
  useEffect(() => {
    let live = true;
    void Promise.all([
      dataProvider.listInsights(),
      dataProvider.listItems(),
      dataProvider.listSources(),
    ])
      .then(([insights, items, sources]) => {
        if (live) setCounts([insights.length, items.length, sources.length]);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [revision]);
  const sidebar = (
    <>
      <div>
        <Link href="/insights" className="brand">
          <span className="brand-mark">
            <BrandMark size={32} />
          </span>
          <span>
            <strong>Flare</strong>
            <small>{t("startupContext")}</small>
          </span>
        </Link>
        <button
          className="button primary sidebar-capture"
          onClick={() => {
            setDrawer(false);
            openCapture();
          }}
        >
          <Icon name="plus" />
          {t("capture")}<kbd>⌘K</kbd>
        </button>
        <nav aria-label={t("primaryNavigation")}>
          {navigation.map((entry, i) => (
            <Link
              key={entry.href}
              href={entry.href}
              onClick={() => setDrawer(false)}
              aria-current={pathname === entry.href ? "page" : undefined}
              className={`nav-link ${pathname === entry.href ? "active" : ""}`}
            >
              <Icon name={entry.icon} />
              <span>{t(entry.label)}</span>
              {i < 3 && <span className="count">{counts[i]}</span>}
            </Link>
          ))}
        </nav>
      </div>
      <div className="sidebar-footer">
        <label className="theme-row">
          <Icon name="moon" />
          <span>{t("darkMode")}</span>
          <input
            className="switch"
            type="checkbox"
            checked={dark}
            onChange={() => setTheme(dark ? "light" : "dark")}
            aria-label={t("darkMode")}
          />
        </label>
        <div className="profile-row">
          <Link href="/settings" className="profile" onClick={() => setDrawer(false)}>
            <span className="avatar">{initials}</span>
            <span className="profile-copy">
              {profile.name || t("unnamedProfile")}
              <small>{profile.role || t("noRole")}</small>
            </span>
          </Link>
          <Link
            href="/settings"
            className="button icon-button profile-settings"
            aria-label={t("settings")}
            title={t("settings")}
            data-funny-sound="off"
            onClick={(event) => {
              if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              if (pathname === "/settings") event.preventDefault();
              setDrawer(false);
              settingsPresses.current += 1;
              if (settingsPresses.current === 10) {
                settingsPresses.current = 0;
                setFunnyMode(!funnyMode);
              }
            }}
          >
            <Icon name="settings" />
          </Link>
        </div>
      </div>
    </>
  );
  return (
    <>
      <a href="#main-content" className="skip-link">
        {t("skipToContent")}
      </a>
      <aside className="sidebar">{sidebar}</aside>
      <button
        className="mobile-menu icon-button"
        aria-label={t("openNavigation")}
        onClick={() => setDrawer(true)}
      >
        <Icon name="menu" />
      </button>
      {drawer && (
        <Dialog
          title={t("navigation")}
          className="nav-drawer"
          onClose={() => setDrawer(false)}
        >
          <button
            className="icon-button drawer-close"
            aria-label={t("closeNavigation")}
            onClick={() => setDrawer(false)}
          >
            <Icon name="close" />
          </button>
          {sidebar}
        </Dialog>
      )}
      <Capture />
      <FunnyEffects />
      <main id="main-content" className="workspace">
        {children}
      </main>
      {notice && (
        <div role="status" className="toast">
          {message(notice)}
        </div>
      )}
    </>
  );
}
