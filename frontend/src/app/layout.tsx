import { Suspense } from "react";
import { AcquisitionCapture } from "@/features/auth/acquisition-capture";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { parseLocale, LOCALE_COOKIE } from "@/i18n/config";
import { I18nProvider } from "@/i18n/provider";
import "./globals.css";
export const metadata: Metadata = {
  title: "Flare — Startup Context",
  description:
    "A calm place to capture startup context and surface grounded Flares.",
};
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = parseLocale((await cookies()).get(LOCALE_COOKIE)?.value);
  return (
    <html lang={locale}>
      <body><Suspense fallback={null}><AcquisitionCapture /></Suspense><I18nProvider initialLocale={locale}>{children}</I18nProvider></body>
    </html>
  );
}
