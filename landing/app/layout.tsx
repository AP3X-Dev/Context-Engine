import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://oni.bot"),
  title: {
    template: "%s | ONI",
    default: "ONI — Agent Infrastructure",
  },
  description: "Tools for building, running, and scaling AI agents",
  openGraph: {
    type: "website",
    locale: "en_US",
    siteName: "ONI",
    images: [{ url: "https://oni.bot/api/og?variant=brand", width: 1200, height: 630 }],
  },
  twitter: {
    card: "summary_large_image",
    site: "@onidotbot",
  },
  icons: { icon: "/favicon.ico" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
