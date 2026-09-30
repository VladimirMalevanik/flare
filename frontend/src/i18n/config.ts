export const SUPPORTED_LOCALES = ["en", "es"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_COOKIE = "flare-locale";
export const LOCALE_NAMES: Record<Locale, string> = { en: "English", es: "Español" };

export function parseLocale(value: string | undefined | null): Locale {
  return SUPPORTED_LOCALES.find((locale) => locale === value) ?? DEFAULT_LOCALE;
}
