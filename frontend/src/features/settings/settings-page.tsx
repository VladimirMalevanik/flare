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
import { LanguageSelector } from "@/components/language-selector";
import { Select } from "@/components/select";
import { useI18n } from "@/i18n/provider";
import { playFunnySound } from "@/features/funny/funny-sounds";
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
export function SettingsPage({ supportEmail, subscription }: { supportEmail: string | null; subscription?: ReactNode }) {
  const { locale, t, label, message: localizeMessage } = useI18n();
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
    funnyMode,
    setFunnyMode,
    funnySounds,
    setFunnySounds,
    funnyAudioPaused,
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
    ? new Intl.DateTimeFormat(locale, {
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
          <h1>{t("Settings")}</h1>
          <p>{t("Manage your profile, workspace preferences, and privacy controls.")}</p>
        </div>
        <span role="status" className="saved-status">
          <Icon name="check" />
          {localizeMessage(message)}
        </span>
      </header>
      <SettingsSection
        title={t("Profile & Account")}
        subtitle={t("Personal identity details for your workspace.")}
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
              {t("Full Name")}{" "}<input
                readOnly={Boolean(session)}
                value={profile.name}
                maxLength={100}
                onChange={(e) => updateProfile({ name: e.target.value })}
              />
            </label>
            <label>
              {t("Work Email")}{" "}<input
                type="email"
                readOnly={Boolean(session)}
                value={profile.email}
                onChange={(e) => updateProfile({ email: e.target.value })}
              />
            </label>
            <label>
              {t("Role / Position")}{" "}<input
                readOnly={Boolean(session)}
                value={profile.role}
                onChange={(e) => updateProfile({ role: e.target.value })}
              />
            </label>
            <label>
              {t("Timezone")}{" "}<Select
                aria-label={t("Timezone")}
                value={profile.timezone}
                onValueChange={(timezone) => updateProfile({ timezone })}
                options={[...new Set([profile.timezone, "Europe/Moscow", "America/Los_Angeles", "Europe/London", "Asia/Singapore"])].map((value) => ({ value, label: value }))}
              />
            </label>
          </div>
        </div>
        {session && <button className="button" onClick={logout} disabled={loggingOut}>{loggingOut ? t("Signing out…") : t("Sign out")}</button>}
      </SettingsSection>
      {subscription}
      <SettingsSection
        title={t("Appearance & Theme")}
        subtitle={t("Customize how Flare looks on your display.")}
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
                {label(choice.label)}
                {theme === choice.id && <Icon name="check" />}
              </span>
              <small>{label(choice.description)}</small>
            </button>
          ))}
        </div>
        <SettingRow title={t("language")} description={t("languageDescription")}>
          <LanguageSelector compact={false} />
        </SettingRow>
        <SettingRow
          title={t("Funny mode")}
          description={t("More color. A Magic 8-ball. Same real Flares. Shake the ball to start a new analysis. Saved in this browser.")}
        >
          <input
            className="switch"
            type="checkbox"
            aria-label={t("Funny mode")}
            checked={funnyMode}
            data-funny-sound="off"
            onChange={(event) => {
              setFunnyMode(event.target.checked);
              playFunnySound("enable", event.target.checked && funnySounds && !funnyAudioPaused);
            }}
          />
        </SettingRow>
        <SettingRow
          title={t("Funny sounds")}
          description={t("Tiny button boops and an English voice nudge. Always quiet while recording voice.")}
        >
          <input
            className="switch"
            type="checkbox"
            aria-label={t("Funny sounds")}
            checked={funnySounds}
            disabled={!funnyMode}
            data-funny-sound="off"
            onChange={(event) => {
              setFunnySounds(event.target.checked);
              playFunnySound("enable", event.target.checked && funnyMode && !funnyAudioPaused);
            }}
          />
        </SettingRow>
        <SettingRow
          title={t("Compact interface density")}
          description={t("Reduce card padding and spacing across your workspace.")}
        >
          <input
            className="switch"
            type="checkbox"
            aria-label={t("Compact interface density")}
            checked={compact}
            onChange={(e) => setCompact(e.target.checked)}
          />
        </SettingRow>
        <SettingRow
          title={t("captureSize")}
          description={t("captureSizeDescription")}
        >
          <div className="orb-size-options" role="group" aria-label={t("captureSize")}>
            {(
              [
                ["small", t("small")],
                ["medium", t("medium")],
                ["large", t("large")],
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
        title={t("In-app notifications")}
        subtitle={t("Choose which updates appear in your workspace.")}
        icon="insights"
      >
        <SettingRow
          title={t("Alerts for important Flares")}
          description={t("A nudge when enough evidence points to something worth reviewing.")}
        >
          <input
            type="checkbox"
            className="switch"
            aria-label={t("Instant alerts")}
            checked={settings.alerts}
            onChange={(e) => update("alerts", e.target.checked)}
          />
        </SettingRow>
      </SettingsSection>
      <SettingsSection
        title={t("Daily insight")}
        subtitle={t("Choose one workspace insight time. Flare freezes the latest supported source versions 30 minutes beforehand.")}
        icon="insights"
      >
        {scheduleLoading ? (
          <p className="muted" role="status">{t("Loading daily insight schedule…")}</p>
        ) : (
          <>
            <SettingRow
              title={t("Automatic daily insight")}
              description={t("At most one insight run is allowed per workspace day, including manual Analyze.")}
            >
              <input
                type="checkbox"
                className="switch"
                aria-label={t("Automatic daily insight")}
                checked={scheduleEnabled}
                disabled={scheduleSaving || session?.workspace.role === "viewer"}
                onChange={(event) => setScheduleEnabled(event.target.checked)}
              />
            </SettingRow>
            <SettingRow
              title={t("Insight time")}
              description={t("If today’s 30-minute preparation window has passed, the first run is scheduled for tomorrow.")}
            >
              <input
                type="time"
                aria-label={t("Daily insight time")}
                value={scheduleTime}
                disabled={scheduleSaving || !scheduleEnabled || session?.workspace.role === "viewer"}
                onChange={(event) => setScheduleTime(event.target.value)}
              />
            </SettingRow>
            <SettingRow
              title={t("Workspace timezone")}
              description={t("The daily limit and schedule follow this timezone.")}
            >
              <Select
                aria-label={t("Daily insight timezone")}
                value={scheduleTimezone}
                disabled={scheduleSaving || !scheduleEnabled || session?.workspace.role === "viewer"}
                onValueChange={setScheduleTimezone}
                options={timezoneOptions.map((value) => ({ value, label: value }))}
              />
            </SettingRow>
            <SettingRow
              title={t("Email new scheduled Flares")}
              description={t("Send one email to your verified account address when a scheduled run creates at least one Flare.")}
            >
              <input
                type="checkbox"
                className="switch"
                aria-label={t("Email new scheduled Flares")}
                checked={scheduleEmailNotifications}
                disabled={scheduleSaving || session?.workspace.role === "viewer"}
                onChange={(event) => setScheduleEmailNotifications(event.target.checked)}
              />
            </SettingRow>
            {analysisSchedule?.enabled && (
              <div className="schedule-preview" aria-live="polite">
                <span><strong>{t("Next refresh")}</strong>{scheduleDate(analysisSchedule.nextRefreshAt)}</span>
                <span><strong>{t("Next insight")}</strong>{scheduleDate(analysisSchedule.nextRunAt)}</span>
              </div>
            )}
            <p className="muted meta">
              {t("Notes and CSV/TXT/Markdown are included. GitHub repository content is not imported yet; its connection currently stores metadata only.")}</p>
            <div className="form-actions schedule-actions">
              {scheduleMessage && (
                <p
                  className={scheduleError ? "error-text meta" : "muted meta"}
                  role={scheduleError ? "alert" : "status"}
                >
                  {localizeMessage(scheduleMessage)}
                </p>
              )}
              <button
                type="button"
                className="button primary"
                disabled={scheduleSaving || !scheduleTime || !scheduleTimezone || session?.workspace.role === "viewer"}
                onClick={() => void saveAnalysisSchedule()}
              >
                {scheduleSaving ? t("Saving…") : t("Save insight schedule")}
              </button>
            </div>
          </>
        )}
      </SettingsSection>
      <SettingsSection
        title={t("Data & Privacy")}
        subtitle={t("Preferences for future connected sources; no live ingestion is running.")}
        icon="settings"
      >
        <SettingRow
          title={t("Exclude direct messages and private channels")}
          description={t("Keep connected context scoped to public team conversations.")}
        >
          <input
            type="checkbox"
            className="switch"
            aria-label={t("Exclude private channels")}
            checked={settings.privateChannels}
            onChange={(e) => update("privateChannels", e.target.checked)}
          />
        </SettingRow>
        <SettingRow
          title={t("Workspace data retention")}
          description={t("Saved preference; automatic deletion is not enabled.")}
        >
          <Select
            aria-label={t("Data retention")}
            value={settings.retention}
            onValueChange={(value) => update("retention", value)}
            options={[{ value: "30", label: t("30 days rolling memory") }, { value: "90", label: t("90 days rolling memory") }, { value: "365", label: t("1 year") }]}
          />
        </SettingRow>
        <SettingRow
          title={t("Export workspace data")}
          description={t("Download active workspace Notes and Flares as Markdown and JSON in a ZIP file.")}
        >
          {session?.workspace.role === "owner" ? (
            <a className="button" href={`${apiBaseUrl}/export`} download>
              {t("Download ZIP")}</a>
          ) : (
            <span className="muted">{t("Owner only")}</span>
          )}
        </SettingRow>
      </SettingsSection>
      <SettingsSection
        title={t("Import guides")}
        subtitle={t("Prepare Notion and Obsidian ZIP snapshots or an Evernote file for import.")}
        icon="file"
      >
        {(["notion", "obsidian", "evernote"] as const).map((source) => (
          <SettingRow
            key={source}
            title={source[0].toUpperCase() + source.slice(1)}
            description={t(source === "evernote" ? "Current imports accept one Markdown, text, or CSV file up to 200 KB." : "Import a ZIP snapshot with .md, .markdown, .txt, and .csv files from Sources.")}
          >
            <Link className="button" href={`/settings/import-guides/${source}`}>
              {t("View guide")}</Link>
          </SettingRow>
        ))}
      </SettingsSection>
      <SettingsSection
        title={t("Workspace & Projects")}
        subtitle={t("Your current workspace and connected project context.")}
        icon="sources"
      >
        <SettingRow
          title={session?.workspace.name ?? "Northstar"}
          description={session ? t("workspaceRole", { role: label(session.workspace.role) }) : t("Personal demo workspace")}
        >
          <span className="badge status-connected">
            <span className="dot" />
            {" "}{t("Active")}</span>
        </SettingRow>
        <p className="meta muted">{t("Workspace tags")}</p>
        <div className="tags">
          <span>{t("Product")}</span>
          <span>{t("Customer Research")}</span>
          <span>{t("Launch")}</span>
        </div>
      </SettingsSection>
      <SettingsSection
        title={t("Support")}
        subtitle={t("Get help with your Flare workspace.")}
        icon="insights"
        className="support-section"
      >
        {supportEmail && (
          <SettingRow
            title={supportEmail}
            description={t("Flare support email")}
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
              {supportCopied ? t("Copied") : t("Copy")}
            </button>
          </SettingRow>
        )}
        <SettingRow
          title={t("Get help")}
          description={
            supportEmail
              ? t("Open your email app to contact the Flare support team.")
              : t("The support address will be available after launch.")
          }
        >
          {supportEmail ? (
            <a className="button" href={`mailto:${supportEmail}?subject=${encodeURIComponent("Flare support request")}`}>
              {t("Contact support")}</a>
          ) : (
            <span className="muted">{t("Not configured")}</span>
          )}
        </SettingRow>
        <SettingRow
          title={t("Send feedback")}
          description={supportEmail ? t("Share product feedback with the Flare team.") : t("The feedback address will be available after launch.")}
        >
          {supportEmail ? (
            <a className="button" href={`mailto:${supportEmail}?subject=${encodeURIComponent("Flare product feedback")}`}>
              {t("Send feedback")}</a>
          ) : (
            <span className="muted">{t("Not configured")}</span>
          )}
        </SettingRow>
        <SettingRow
          title={t("Legal")}
          description={t("Review how Flare handles your data and the terms for using the service.")}
        >
          <span className="legal-inline-links">
            <Link className="button" href="/privacy">{t("Privacy")}</Link>
            <Link className="button" href="/terms">{t("Terms")}</Link>
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
