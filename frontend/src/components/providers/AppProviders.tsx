"use client";

import type { ReactNode } from "react";

import { AntdProvider } from "@/components/providers/AntdProvider";
import { QueryProvider } from "@/components/providers/QueryProvider";

interface AppProvidersProps {
  children: ReactNode;
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <QueryProvider>
      <AntdProvider>{children}</AntdProvider>
    </QueryProvider>
  );
}
