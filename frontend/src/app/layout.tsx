import { Suspense } from "react";
import { AcquisitionCapture } from "@/features/auth/acquisition-capture";
import { SiteAnalytics } from "@/features/telemetry/site-analytics";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { parseLocale, LOCALE_COOKIE } from "@/i18n/config";
import { I18nProvider } from "@/i18n/provider";
import "./globals.css";
export const metadata: Metadata = {
  title: "Flare — Startup Context",
  description:
    "A calm place to capture startup context and surface grounded Flares.",
  openGraph: {
    type: "website",
    url: "https://flare4u.tech",
    siteName: "Flare",
    title: "Your notes go quiet. Flare doesn't.",
    description: "Capture decisions, research, calls, and loose thoughts. Insights backed by your own sources.",
    images: [{
      url: "https://flare4u.tech/brand/flare-link-cover.jpg",
      width: 1200,
      height: 630,
      type: "image/jpeg",
      alt: "Flare — Your notes go quiet. Flare doesn't. Insights backed by your own sources.",
    }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Your notes go quiet. Flare doesn't.",
    description: "Capture decisions, research, calls, and loose thoughts. Insights backed by your own sources.",
    images: [{
      url: "https://flare4u.tech/brand/flare-link-cover.jpg",
      alt: "Flare — Your notes go quiet. Flare doesn't. Insights backed by your own sources.",
    }],
  },
};
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const locale = parseLocale((await cookies()).get(LOCALE_COOKIE)?.value);
  return (
    <html lang={locale}>
      <body>
        <I18nProvider initialLocale={locale}>
          <Suspense fallback={null}><AcquisitionCapture /></Suspense>
          <Suspense fallback={null}><SiteAnalytics /></Suspense>
          {children}
        </I18nProvider>
      </body>
    </html>
  );
}
