import type { UserSettings } from "@/features/user/api/userApi";
import type { ThemeMode } from "@/stores/themeStore";

const DEFAULT_THEME: ThemeMode = "system";

/** 서버 Preferences theme → FE ThemeMode */
export function applyThemeFromSettings(
  settings: Pick<UserSettings, "theme">,
): ThemeMode {
  const theme = settings.theme;
  if (theme === "light" || theme === "dark" || theme === "system") {
    return theme;
  }
  return DEFAULT_THEME;
}
