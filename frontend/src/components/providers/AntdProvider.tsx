"use client";

import { AntdRegistry } from "@ant-design/nextjs-registry";
import { App, ConfigProvider } from "antd";
import type { ReactNode } from "react";

import { useThemeMode } from "@/hooks/useThemeMode";
import { resolveAntdTheme } from "@/styles/theme";

interface AntdProviderProps {
  children: ReactNode;
}

export function AntdProvider({ children }: AntdProviderProps) {
  const { isDark } = useThemeMode();

  return (
    <AntdRegistry>
      <ConfigProvider theme={resolveAntdTheme(isDark)}>
        <App>{children}</App>
      </ConfigProvider>
    </AntdRegistry>
  );
}
