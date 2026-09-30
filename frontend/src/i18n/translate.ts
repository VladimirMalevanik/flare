import { DEFAULT_LOCALE, parseLocale, type Locale } from "./config";
import { en, type TranslationKey } from "./en";
import { es } from "./es";

export const dictionaries = { en, es } satisfies Record<Locale, Record<TranslationKey, string>>;
export type Translation = (key: TranslationKey, values?: Record<string, string | number>) => string;

export function translate(locale: Locale | undefined, key: TranslationKey, values?: Record<string, string | number>): string {
  return dictionaries[parseLocale(locale ?? DEFAULT_LOCALE)][key].replace(/\{(\w+)\}/g, (match, name: string) =>
    values?.[name] === undefined ? match : String(values[name]));
}

/** For frontend-owned catalog/status labels only. Never pass workspace content. */
export function localizeLabel(locale: Locale, value: string): string {
  return Object.hasOwn(en, value) ? translate(locale, value as TranslationKey) : value;
}

/** Unknown failures use a localized fallback, never raw server error text. */
export function localizeMessage(locale: Locale, value: string): string {
  return Object.hasOwn(en, value) ? translate(locale, value as TranslationKey) : translate(locale, "genericError");
}

export function relativeTime(locale: Locale, date: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(date).getTime()) / 60_000));
  if (minutes < 1) return translate(locale, "justNow");
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (minutes < 60) return format.format(-minutes, "minute");
  if (minutes < 1440) return format.format(-Math.round(minutes / 60), "hour");
  return format.format(-Math.round(minutes / 1440), "day");
}
