import type { Metadata } from "next";

import { AppProviders } from "@/components/providers/AppProviders";
import { env } from "@/config/env";
import "@/styles/globals.css";

export const metadata: Metadata = {
  title: env.APP_NAME,
  description: "KIKI AI Trading Platform — User & Admin",
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
