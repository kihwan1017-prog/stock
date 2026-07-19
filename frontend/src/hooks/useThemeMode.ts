"use client";

import { useEffect, useState } from "react";

import { useThemeStore, type ThemeMode } from "@/stores/themeStore";

function getSystemPrefersDark(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function useThemeMode() {
  const mode = useThemeStore((state) => state.mode);
  const setMode = useThemeStore((state) => state.setMode);
  const [resolvedDark, setResolvedDark] = useState(false);

  useEffect(() => {
    const apply = (currentMode: ThemeMode) => {
      const isDark = currentMode === "dark" || (currentMode === "system" && getSystemPrefersDark());
      setResolvedDark(isDark);
      document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
      document.documentElement.style.colorScheme = isDark ? "dark" : "light";
    };

    apply(mode);

    if (mode !== "system") {
      return;
    }

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [mode]);

  return {
    mode,
    setMode,
    isDark: resolvedDark,
  };
}
