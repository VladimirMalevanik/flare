import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Flare — Startup Context",
  description:
    "A calm place to capture startup context and surface grounded Flares.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
