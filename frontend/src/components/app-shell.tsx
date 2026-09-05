"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "./icons";
import { WorkspaceProvider, useWorkspace } from "./workspace-context";
import { Capture } from "@/features/capture/capture";
import { dataProvider } from "@/lib/data";
import { Dialog } from "./dialog";
const navigation = [
  { href: "/insights", label: "Insights", icon: "insights" },
  { href: "/vault", label: "Vault", icon: "vault" },
  { href: "/sources", label: "Sources", icon: "sources" },
  { href: "/settings", label: "Settings", icon: "settings" },
] as const;
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <WorkspaceProvider>
      <Shell>{children}</Shell>
    </WorkspaceProvider>
  );
}
function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [drawer, setDrawer] = useState(false);
  const { dark, setTheme, openCapture, revision, notice, profile } =
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
            <Icon name="sources" />
          </span>
          <span>
            <strong>Flare</strong>
            <small>AI Research Engine</small>
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
          Capture<kbd>⌘K</kbd>
        </button>
        <nav aria-label="Primary navigation">
          {navigation.map((entry, i) => (
            <Link
              key={entry.href}
              href={entry.href}
              onClick={() => setDrawer(false)}
              aria-current={pathname === entry.href ? "page" : undefined}
              className={`nav-link ${pathname === entry.href ? "active" : ""}`}
            >
              <Icon name={entry.icon} />
              <span>{entry.label}</span>
              {i < 3 && <span className="count">{counts[i]}</span>}
            </Link>
          ))}
        </nav>
      </div>
      <div className="sidebar-footer">
        <label className="theme-row">
          <Icon name="moon" />
          <span>Dark Mode</span>
          <input
            className="switch"
            type="checkbox"
            checked={dark}
            onChange={() => setTheme(dark ? "light" : "dark")}
            aria-label="Dark Mode"
          />
        </label>
        <Link href="/settings" className="profile">
          <span className="avatar">{initials}</span>
          <span>
            {profile.name || "Unnamed profile"}
            <small>{profile.role || "No role set"}</small>
          </span>
          <Icon name="chevron" />
        </Link>
      </div>
    </>
  );
  return (
    <>
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar">{sidebar}</aside>
      <button
        className="mobile-menu icon-button"
        aria-label="Open navigation"
        onClick={() => setDrawer(true)}
      >
        <Icon name="menu" />
      </button>
      {drawer && (
        <Dialog
          title="Navigation"
          className="nav-drawer"
          onClose={() => setDrawer(false)}
        >
          <button
            className="icon-button drawer-close"
            aria-label="Close navigation"
            onClick={() => setDrawer(false)}
          >
            <Icon name="close" />
          </button>
          {sidebar}
        </Dialog>
      )}
      <Capture />
      <main id="main-content" className="workspace">
        {children}
      </main>
      {notice && (
        <div role="status" className="toast">
          {notice}
        </div>
      )}
    </>
  );
}
