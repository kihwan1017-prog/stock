import { describe, expect, it } from "vitest";

import { applyThemeFromSettings } from "@/features/user/settings/settingsHelpers";

describe("STEP72 user settings helpers", () => {
  it("accepts valid themes", () => {
    expect(applyThemeFromSettings({ theme: "dark" })).toBe("dark");
    expect(applyThemeFromSettings({ theme: "light" })).toBe("light");
    expect(applyThemeFromSettings({ theme: "system" })).toBe("system");
  });

  it("falls back on invalid theme", () => {
    expect(applyThemeFromSettings({ theme: "neon" })).toBe("system");
  });
});
