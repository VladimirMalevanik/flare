"use client";
import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSession } from "@/components/auth-session";
import { apiBaseUrl, authRequest } from "@/lib/auth/session";
import { Icon } from "@/components/icons";
import {
  useWorkspace,
  type CaptureOrbSize,
  type Theme,
} from "@/components/workspace-context";
import { readLocal, writeLocal } from "@/lib/storage/preferences";
import {
  dataErrorMessage,
  dataProvider,
  type AnalysisSchedule,
} from "@/lib/data";
const defaults = {
  alerts: true,
  privateChannels: true,
  retention: "30",
  telegram: true,
};
export function SettingsPage({ supportEmail }: { supportEmail: string | null }) {
  const session = useSession();
  const [loggingOut, setLoggingOut] = useState(false);
  async function logout() {
    setLoggingOut(true);
    try {
      await authRequest("logout");
      window.location.replace("/login");
    } catch {
      setMessage("Could not sign out. Please retry.");
      setLoggingOut(false);
    }
  }
  const {
    theme,
    setTheme,
    compact,
    setCompact,
    captureOrbSize,
    setCaptureOrbSize,
    profile,
    updateProfile,
  } = useWorkspace();
  const [settings, setSettings] = useState(defaults);
  const [analysisSchedule, setAnalysisSchedule] = useState<AnalysisSchedule | null>(null);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduleEmailNotifications, setScheduleEmailNotifications] = useState(true);
  const [scheduleTime, setScheduleTime] = useState("19:00");
  const [scheduleTimezone, setScheduleTimezone] = useState(profile.timezone);
  const [scheduleLoading, setScheduleLoading] = useState(true);
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduleMessage, setScheduleMessage] = useState("");
  const [scheduleError, setScheduleError] = useState(false);
  const timezoneOptions = useMemo(() => {
    const extended = Intl as typeof Intl & {
      supportedValuesOf?: (key: "timeZone") => string[];
    };
    const supported = extended.supportedValuesOf?.("timeZone") ?? [
      "Europe/Moscow",
      "Europe/London",
      "America/New_York",
      "America/Los_Angeles",
      "Asia/Singapore",
    ];
    return Array.from(new Set(["UTC", profile.timezone, scheduleTimezone, ...supported])).sort();
  }, [profile.timezone, scheduleTimezone]);
  const [message, setMessage] = useState(
    "Preferences are saved in this browser",
  );
  const [supportCopied, setSupportCopied] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const value = readLocal<Partial<typeof defaults>>(
        "flare-settings-v1",
        {},
      );
      setSettings({
        alerts: value.alerts ?? defaults.alerts,
        privateChannels: value.privateChannels ?? defaults.privateChannels,
        retention: value.retention ?? defaults.retention,
        telegram: value.telegram ?? defaults.telegram,
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    let live = true;
    void dataProvider.getAnalysisSchedule()
      .then((value) => {
        if (!live) return;
        setAnalysisSchedule(value);
        setScheduleEnabled(value.enabled);
        setScheduleEmailNotifications(value.emailNotificationsEnabled);
        setScheduleTime(value.localTime);
        setScheduleTimezone(value.timezone);
        setScheduleMessage("");
        setScheduleError(false);
      })
      .catch((error) => {
        if (live) {
          setScheduleError(true);
          setScheduleMessage(dataErrorMessage(error, "Daily insight schedule could not be loaded."));
        }
      })
      .finally(() => {
        if (live) setScheduleLoading(false);
      });
    return () => { live = false; };
  }, []);
  async function saveAnalysisSchedule() {
    if (scheduleSaving) return;
    setScheduleSaving(true);
    setScheduleMessage("");
    setScheduleError(false);
    try {
      const saved = await dataProvider.updateAnalysisSchedule({
        enabled: scheduleEnabled,
        emailNotificationsEnabled: scheduleEmailNotifications,
        timezone: scheduleTimezone,
        localTime: scheduleTime,
      });
      setAnalysisSchedule(saved);
      setScheduleMessage(saved.enabled
        ? "Daily insight scheduled. Saved context is prepared 30 minutes before it runs."
        : "Future automatic daily insights are paused. A run already queued may still finish.");
    } catch (error) {
      setScheduleError(true);
      setScheduleMessage(dataErrorMessage(error, "Daily insight schedule could not be saved."));
    } finally {
      setScheduleSaving(false);
    }
  }
  const scheduleDate = (value: string | null) => value
    ? new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: analysisSchedule?.timezone ?? scheduleTimezone,
      }).format(new Date(value))
    : "—";
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
          <p>Manage your profile, workspace preferences, and privacy controls.</p>
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
                readOnly={Boolean(session)}
                value={profile.name}
                maxLength={100}
                onChange={(e) => updateProfile({ name: e.target.value })}
              />
            </label>
            <label>
              Work Email
              <input
                type="email"
                readOnly={Boolean(session)}
                value={profile.email}
                onChange={(e) => updateProfile({ email: e.target.value })}
              />
            </label>
            <label>
              Role / Position
              <input
                readOnly={Boolean(session)}
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
        {session && <button className="button" onClick={logout} disabled={loggingOut}>{loggingOut ? "Signing out…" : "Sign out"}</button>}
      </SettingsSection>
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
        <SettingRow
          title="Capture orb size"
          description="Choose the size of the floating capture orb."
        >
          <div className="orb-size-options" role="group" aria-label="Capture orb size">
            {(
              [
                ["small", "Small"],
                ["medium", "Medium"],
                ["large", "Large"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                className={`filter ${captureOrbSize === value ? "selected" : ""}`}
                aria-pressed={captureOrbSize === value}
                onClick={() => setCaptureOrbSize(value as CaptureOrbSize)}
              >
                {label}
              </button>
            ))}
          </div>
        </SettingRow>
      </SettingsSection>
      <SettingsSection
        title="In-app notifications"
        subtitle="Choose which updates appear in your workspace."
        icon="insights"
      >
        <SettingRow
          title="Alerts for important Flares"
          description="A nudge when enough evidence points to something worth reviewing."
        >
          <input
            type="checkbox"
            className="switch"
            aria-label="Instant alerts"
            checked={settings.alerts}
            onChange={(e) => update("alerts", e.target.checked)}
          />
        </SettingRow>
      </SettingsSection>
      <SettingsSection
        title="Daily insight"
        subtitle="Choose one workspace insight time. Flare freezes the latest supported source versions 30 minutes beforehand."
        icon="insights"
      >
        {scheduleLoading ? (
          <p className="muted" role="status">Loading daily insight schedule…</p>
        ) : (
          <>
            <SettingRow
              title="Automatic daily insight"
              description="At most one insight run is allowed per workspace day, including manual Analyze."
            >
              <input
                type="checkbox"
                className="switch"
                aria-label="Automatic daily insight"
                checked={scheduleEnabled}
                disabled={scheduleSaving || session?.workspace.role === "viewer"}
                onChange={(event) => setScheduleEnabled(event.target.checked)}
              />
            </SettingRow>
            <SettingRow
              title="Insight time"
              description="If today’s 30-minute preparation window has passed, the first run is scheduled for tomorrow."
            >
              <input
                type="time"
                aria-label="Daily insight time"
                value={scheduleTime}
                disabled={scheduleSaving || !scheduleEnabled || session?.workspace.role === "viewer"}
                onChange={(event) => setScheduleTime(event.target.value)}
              />
            </SettingRow>
            <SettingRow
              title="Workspace timezone"
              description="The daily limit and schedule follow this timezone."
            >
              <select
                aria-label="Daily insight timezone"
                value={scheduleTimezone}
                disabled={scheduleSaving || !scheduleEnabled || session?.workspace.role === "viewer"}
                onChange={(event) => setScheduleTimezone(event.target.value)}
              >
                {timezoneOptions.map((timezone) => (
                  <option value={timezone} key={timezone}>{timezone}</option>
                ))}
              </select>
            </SettingRow>
            <SettingRow
              title="Email new scheduled Flares"
              description="Send one email to your verified account address when a scheduled run creates at least one Flare."
            >
              <input
                type="checkbox"
                className="switch"
                aria-label="Email new scheduled Flares"
                checked={scheduleEmailNotifications}
                disabled={scheduleSaving || session?.workspace.role === "viewer"}
                onChange={(event) => setScheduleEmailNotifications(event.target.checked)}
              />
            </SettingRow>
            {analysisSchedule?.enabled && (
              <div className="schedule-preview" aria-live="polite">
                <span><strong>Next refresh</strong>{scheduleDate(analysisSchedule.nextRefreshAt)}</span>
                <span><strong>Next insight</strong>{scheduleDate(analysisSchedule.nextRunAt)}</span>
              </div>
            )}
            <p className="muted meta">
              Notes and CSV/TXT/Markdown are included. GitHub repository content is not imported yet; its connection currently stores metadata only.
            </p>
            <div className="form-actions schedule-actions">
              {scheduleMessage && (
                <p
                  className={scheduleError ? "error-text meta" : "muted meta"}
                  role={scheduleError ? "alert" : "status"}
                >
                  {scheduleMessage}
                </p>
              )}
              <button
                type="button"
                className="button primary"
                disabled={scheduleSaving || !scheduleTime || !scheduleTimezone || session?.workspace.role === "viewer"}
                onClick={() => void saveAnalysisSchedule()}
              >
                {scheduleSaving ? "Saving…" : "Save insight schedule"}
              </button>
            </div>
          </>
        )}
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
          description="Saved preference; automatic deletion is not enabled."
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
        <SettingRow
          title="Export workspace data"
          description="Download active workspace Notes and Flares as Markdown and JSON in a ZIP file."
        >
          {session?.workspace.role === "owner" ? (
            <a className="button" href={`${apiBaseUrl}/export`} download>
              Download ZIP
            </a>
          ) : (
            <span className="muted">Owner only</span>
          )}
        </SettingRow>
      </SettingsSection>
      <SettingsSection
        title="Import guides"
        subtitle="Prepare exports from other tools for Flare's current file importer."
        icon="file"
      >
        {(["notion", "obsidian", "evernote"] as const).map((source) => (
          <SettingRow
            key={source}
            title={source[0].toUpperCase() + source.slice(1)}
            description="Current imports accept one Markdown, text, or CSV file up to 200 KB."
          >
            <Link className="button" href={`/settings/import-guides/${source}`}>
              View guide
            </Link>
          </SettingRow>
        ))}
      </SettingsSection>
      <SettingsSection
        title="Workspace & Projects"
        subtitle="Your current workspace and connected project context."
        icon="sources"
      >
        <SettingRow
          title={session?.workspace.name ?? "Northstar"}
          description={session ? `Workspace role: ${session.workspace.role}` : "Personal demo workspace"}
        >
          <span className="badge status-connected">
            <span className="dot" />
            Active
          </span>
        </SettingRow>
        <p className="meta muted">Workspace tags</p>
        <div className="tags">
          <span>Product</span>
          <span>Customer Research</span>
          <span>Launch</span>
        </div>
      </SettingsSection>
      <SettingsSection
        title="Support"
        subtitle="Get help with your Flare workspace."
        icon="insights"
        className="support-section"
      >
        {supportEmail && (
          <SettingRow
            title={supportEmail}
            description="Flare support email"
          >
            <button
              type="button"
              className="button support-copy"
              onClick={() => {
                void navigator.clipboard.writeText(supportEmail).then(
                  () => setSupportCopied(true),
                  () => setSupportCopied(false),
                );
              }}
            >
              {supportCopied ? "Copied" : "Copy"}
            </button>
          </SettingRow>
        )}
        <SettingRow
          title="Get help"
          description={
            supportEmail
              ? "Open your email app to contact the Flare support team."
              : "The support address will be available after launch."
          }
        >
          {supportEmail ? (
            <a className="button" href={`mailto:${supportEmail}?subject=${encodeURIComponent("Flare support request")}`}>
              Contact support
            </a>
          ) : (
            <span className="muted">Not configured</span>
          )}
        </SettingRow>
        <SettingRow
          title="Send feedback"
          description={supportEmail ? "Share product feedback with the Flare team." : "The feedback address will be available after launch."}
        >
          {supportEmail ? (
            <a className="button" href={`mailto:${supportEmail}?subject=${encodeURIComponent("Flare product feedback")}`}>
              Send feedback
            </a>
          ) : (
            <span className="muted">Not configured</span>
          )}
        </SettingRow>
        <SettingRow
          title="Legal"
          description="Review how Flare handles your data and the terms for using the service."
        >
          <span className="legal-inline-links">
            <Link className="button" href="/privacy">Privacy</Link>
            <Link className="button" href="/terms">Terms</Link>
          </span>
        </SettingRow>
      </SettingsSection>
    </section>
  );
}
function SettingsSection({
  title,
  subtitle,
  icon,
  className = "",
  children,
}: {
  title: string;
  subtitle: string;
  icon: Parameters<typeof Icon>[0]["name"];
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`card settings-section ${className}`}>
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
      <div className="setting-row-copy">
        <h3>{title}</h3>
        <p className="muted meta">{description}</p>
      </div>
      {children}
    </div>
  );
}
