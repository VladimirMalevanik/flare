"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { LOCALE_COOKIE, parseLocale, type Locale } from "./config";
import { localizeLabel, localizeMessage, translate, type Translation } from "./translate";

type I18nContextValue = { locale: Locale; setLocale: (locale: Locale) => void; t: Translation; label: (value: string) => string; message: (value: string) => string };
const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ initialLocale, children }: { initialLocale: Locale; children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(parseLocale(initialLocale));
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);

  const setLocale = useCallback((value: Locale) => {
    const next = parseLocale(value);
    document.cookie = `${LOCALE_COOKIE}=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
    document.documentElement.lang = next;
    setLocaleState(next);
  }, []);

  const context = useMemo<I18nContextValue>(() => ({
    locale, setLocale,
    t: (key, values) => translate(locale, key, values),
    label: (value) => localizeLabel(locale, value),
    message: (value) => localizeMessage(locale, value),
  }), [locale, setLocale]);
  return <I18nContext.Provider value={context}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error("I18nProvider is missing");
  return context;
}
