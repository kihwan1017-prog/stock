import type { Metadata, Viewport } from "next";

import { AppProviders } from "@/components/providers/AppProviders";
import { env } from "@/config/env";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: env.APP_NAME,
  description: "KIKI AI Trading Platform — User & Admin",
  applicationName: "Stock Platform",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    title: "Stock",
    statusBarStyle: "black-translucent",
  },
};

export const viewport: Viewport = {
  themeColor: "#0f1419",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
