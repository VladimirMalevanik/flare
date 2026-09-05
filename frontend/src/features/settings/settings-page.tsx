"use client";
import { useEffect, useState, type ReactNode } from "react";
import { Icon } from "@/components/icons";
import { Dialog } from "@/components/dialog";
import { useWorkspace, type Theme } from "@/components/workspace-context";
import { readLocal, writeLocal } from "@/lib/storage/preferences";
const defaults = {
  alerts: true,
  digest: true,
  privateChannels: true,
  retention: "30",
  telegram: true,
  emailDelivery: true,
};
export function SettingsPage() {
  const { theme, setTheme, compact, setCompact, profile, updateProfile } =
    useWorkspace();
  const [settings, setSettings] = useState(defaults);
  const [billingOpen, setBillingOpen] = useState(false);
  const [message, setMessage] = useState(
    "Preferences are saved in this browser",
  );
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const value = readLocal<Partial<typeof defaults>>(
        "flare-settings-v1",
        {},
      );
      setSettings({
        alerts: value.alerts ?? defaults.alerts,
        digest: value.digest ?? defaults.digest,
        privateChannels: value.privateChannels ?? defaults.privateChannels,
        retention: value.retention ?? defaults.retention,
        telegram: value.telegram ?? defaults.telegram,
        emailDelivery: value.emailDelivery ?? defaults.emailDelivery,
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  function update<K extends keyof typeof defaults>(
    key: K,
    value: (typeof defaults)[K],
  ) {
    const next = { ...settings, [key]: value };
    setSettings(next);
    try {
      writeLocal("flare-settings-v1", next);
      setMessage("All changes saved locally");
    } catch {
      setMessage("Could not save preferences. Browser storage is unavailable.");
    }
  }
  return (
    <section className="page settings-page">
      <header className="page-heading heading-row">
        <div>
          <h1>Settings</h1>
          <p>
            Manage your profile, workspace preferences, and privacy controls.
          </p>
        </div>
        <span role="status" className="saved-status">
          <Icon name="check" />
          {message}
        </span>
      </header>
      <SettingsSection
        title="Profile & Account"
        subtitle="Personal identity details for your workspace."
        icon="home"
      >
        <div className="profile-editor">
          <span className="avatar large">
            {profile.name
              .split(" ")
              .map((p) => p[0])
              .slice(0, 2)
              .join("")}
          </span>
          <div className="field-grid">
            <label>
              Full Name
              <input
                value={profile.name}
                maxLength={100}
                onChange={(e) => updateProfile({ name: e.target.value })}
              />
            </label>
            <label>
              Work Email
              <input
                type="email"
                value={profile.email}
                onChange={(e) => updateProfile({ email: e.target.value })}
              />
            </label>
            <label>
              Role / Position
              <input
                value={profile.role}
                onChange={(e) => updateProfile({ role: e.target.value })}
              />
            </label>
            <label>
              Timezone
              <select
                value={profile.timezone}
                onChange={(e) => updateProfile({ timezone: e.target.value })}
              >
                <option>Europe/Moscow</option>
                <option>America/Los_Angeles</option>
                <option>Europe/London</option>
                <option>Asia/Singapore</option>
              </select>
            </label>
          </div>
        </div>
      </SettingsSection>
      <SettingsSection
        title="Plan & Billing"
        subtitle="Demo only. No payments or subscriptions are connected."
        icon="file"
      >
        <SettingRow title="Current plan" description="Not configured">
          <span className="badge">Mock</span>
        </SettingRow>
        <SettingRow title="Billing status" description="Not connected">
          <button className="button" onClick={() => setBillingOpen(true)}>
            Manage billing
          </button>
        </SettingRow>
        <SettingRow
          title="Payment method"
          description="No payment method on file"
        >
          <span className="muted">—</span>
        </SettingRow>
        <SettingRow title="Invoices" description="No invoices yet">
          <span className="muted">—</span>
        </SettingRow>
      </SettingsSection>
      {billingOpen && (
        <Dialog title="Manage billing" onClose={() => setBillingOpen(false)}>
          <header className="sheet-header">
            <h2>Manage billing</h2>
            <button
              className="icon-button"
              aria-label="Close billing"
              onClick={() => setBillingOpen(false)}
            >
              <Icon name="close" />
            </button>
          </header>
          <p>
            Billing is not connected in this demo. There is no active
            subscription, saved payment method, or invoice history.
          </p>
          <p className="muted">
            No payment details are collected and no charges can be made.
          </p>
        </Dialog>
      )}
      <SettingsSection
        title="Appearance & Theme"
        subtitle="Customize how Flare looks on your display."
        icon="sun"
      >
        <div className="theme-options">
          {(
            [
              {
                id: "system",
                label: "System default",
                description: "Matches OS preference",
                icon: "system",
              },
              {
                id: "light",
                label: "Light mode",
                description: "High clarity porcelain canvas",
                icon: "sun",
              },
              {
                id: "dark",
                label: "Dark mode",
                description: "Reduced glare for low light",
                icon: "moon",
              },
            ] as const
          ).map((choice) => (
            <button
              key={choice.id}
              className={`theme-option ${theme === choice.id ? "active" : ""}`}
              aria-pressed={theme === choice.id}
              onClick={() => setTheme(choice.id as Theme)}
            >
              <span className={`theme-preview preview-${choice.id}`}>
                <Icon name={choice.icon} />
              </span>
              <span>
                {choice.label}
                {theme === choice.id && <Icon name="check" />}
              </span>
              <small>{choice.description}</small>
            </button>
          ))}
        </div>
        <SettingRow
          title="Compact interface density"
          description="Reduce card padding and spacing across your workspace."
        >
          <input
            className="switch"
            type="checkbox"
            aria-label="Compact interface density"
            checked={compact}
            onChange={(e) => setCompact(e.target.checked)}
          />
        </SettingRow>
      </SettingsSection>
      <SettingsSection
        title="Notifications & Digest"
        subtitle="Choose which updates you want to receive. Delivery is mocked."
        icon="insights"
      >
        <SettingRow
          title="Instant alerts for critical contradictions"
          description="A nudge when new context conflicts with an earlier decision."
        >
          <input
            type="checkbox"
            className="switch"
            aria-label="Instant alerts"
            checked={settings.alerts}
            onChange={(e) => update("alerts", e.target.checked)}
          />
        </SettingRow>
        <SettingRow
          title="Daily morning context synthesis digest"
          description="A daily summary at 08:30 in your selected timezone."
        >
          <input
            className="switch"
            type="checkbox"
            aria-label="Daily digest"
            checked={settings.digest}
            onChange={(e) => update("digest", e.target.checked)}
          />
        </SettingRow>
        <SettingRow
          title="Delivery destinations"
          description="Channels selected for your brief."
        >
          <div className="tags">
            {(["telegram", "emailDelivery"] as const).map((key) => (
              <button
                key={key}
                className={`filter ${settings[key] ? "selected" : ""}`}
                aria-pressed={settings[key]}
                onClick={() => update(key, !settings[key])}
              >
                {key === "telegram" ? "Telegram" : "Email"}
              </button>
            ))}
          </div>
        </SettingRow>
      </SettingsSection>
      <SettingsSection
        title="Data & Privacy"
        subtitle="Preferences for future connected sources; no live ingestion is running."
        icon="settings"
      >
        <SettingRow
          title="Exclude direct messages and private channels"
          description="Keep connected context scoped to public team conversations."
        >
          <input
            type="checkbox"
            className="switch"
            aria-label="Exclude private channels"
            checked={settings.privateChannels}
            onChange={(e) => update("privateChannels", e.target.checked)}
          />
        </SettingRow>
        <SettingRow
          title="Workspace data retention"
          description="Saved preference; automatic deletion is not enabled in this demo."
        >
          <select
            aria-label="Data retention"
            value={settings.retention}
            onChange={(e) => update("retention", e.target.value)}
          >
            <option value="30">30 days rolling memory</option>
            <option value="90">90 days rolling memory</option>
            <option value="365">1 year</option>
          </select>
        </SettingRow>
      </SettingsSection>
      <SettingsSection
        title="Workspace & Projects"
        subtitle="Your current workspace and connected project context."
        icon="sources"
      >
        <SettingRow
          title="Acme Core Platform"
          description="Personal demo workspace"
        >
          <span className="badge status-connected">
            <span className="dot" />
            Active
          </span>
        </SettingRow>
        <p className="meta muted">Monitored projects</p>
        <div className="tags">
          <span>flare-core</span>
          <span>sync-engine</span>
          <span>mobile-v4</span>
        </div>
      </SettingsSection>
    </section>
  );
}
function SettingsSection({
  title,
  subtitle,
  icon,
  children,
}: {
  title: string;
  subtitle: string;
  icon: Parameters<typeof Icon>[0]["name"];
  children: ReactNode;
}) {
  return (
    <section className="card settings-section">
      <header>
        <h2>
          <Icon name={icon} />
          {title}
        </h2>
        <p className="muted meta">{subtitle}</p>
      </header>
      {children}
    </section>
  );
}
function SettingRow({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="setting-row">
      <div>
        <h3>{title}</h3>
        <p className="muted meta">{description}</p>
      </div>
      {children}
    </div>
  );
}
