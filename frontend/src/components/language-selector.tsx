"use client";

import { useI18n } from "@/i18n/provider";
import { LOCALE_NAMES, SUPPORTED_LOCALES, parseLocale } from "@/i18n/config";

export function LanguageSelector({ compact = true }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <label className={`language-selector ${compact ? "language-selector--compact" : ""}`}>
      <span className="sr-only">{t("language")}</span>
      <select aria-label={t("language")} value={locale} onChange={(event) => setLocale(parseLocale(event.target.value))}>
        {SUPPORTED_LOCALES.map((value) => (
          <option key={value} value={value}>{compact ? value.toUpperCase() : LOCALE_NAMES[value]}</option>
        ))}
      </select>
    </label>
  );
}
