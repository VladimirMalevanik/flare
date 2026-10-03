"use client";

import { useI18n } from "@/i18n/provider";
import { LOCALE_NAMES, SUPPORTED_LOCALES, parseLocale } from "@/i18n/config";

export function LanguageSelector({ compact = true }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <label className={`language-selector ${compact ? "language-selector--compact" : ""}`}>
      <span className="sr-only">{t("language")}</span>
      <svg aria-hidden="true" className="language-selector-globe" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18" /></svg>
      <select aria-label={t("language")} value={locale} onChange={(event) => setLocale(parseLocale(event.target.value))}>
        {SUPPORTED_LOCALES.map((value) => (
          <option key={value} value={value}>{LOCALE_NAMES[value]}</option>
        ))}
      </select>
      <svg aria-hidden="true" className="language-selector-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="m4 6 4 4 4-4" /></svg>
    </label>
  );
}
