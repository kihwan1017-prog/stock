"use client";

import type { ReactNode } from "react";

import { AntdProvider } from "@/components/providers/AntdProvider";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { MobileBootRecoveryGate } from "@/features/mobile/MobileBootRecoveryGate";

interface AppProvidersProps {
  children: ReactNode;
}

export function AppProviders({ children }: AppProvidersProps) {
  return (
    <QueryProvider>
      <AntdProvider>
        <MobileBootRecoveryGate />
        {children}
      </AntdProvider>
    </QueryProvider>
  );
}
