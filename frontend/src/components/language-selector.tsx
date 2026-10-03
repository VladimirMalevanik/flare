"use client";

import { useI18n } from "@/i18n/provider";
import { LOCALE_NAMES, SUPPORTED_LOCALES, parseLocale } from "@/i18n/config";
import { Select } from "@/components/select";

const languages = SUPPORTED_LOCALES.map((value) => ({ value, label: LOCALE_NAMES[value] }));

export function LanguageSelector({ compact = true }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n();
  return (
    <Select
      className="language-selector" variant={compact ? "compact" : "field"} align="end"
      aria-label={t("language")} value={locale} options={languages}
      onValueChange={(value) => setLocale(parseLocale(value))}
      icon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18" /></svg>}
    />
  );
}
