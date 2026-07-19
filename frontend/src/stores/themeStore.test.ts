import { beforeEach, describe, expect, it } from "vitest";

import { useThemeStore } from "@/stores/themeStore";

describe("themeStore", () => {
  beforeEach(() => {
    useThemeStore.setState({ mode: "system" });
    localStorage.clear();
  });

  it("defaults to system", () => {
    expect(useThemeStore.getState().mode).toBe("system");
  });

  it("updates theme mode", () => {
    useThemeStore.getState().setMode("dark");
    expect(useThemeStore.getState().mode).toBe("dark");
  });
});
