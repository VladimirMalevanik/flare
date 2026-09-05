import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Flare — AI Second Brain",
  description:
    "A calm place to capture, retrieve, and surface grounded insights.",
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
