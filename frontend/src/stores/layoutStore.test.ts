import { beforeEach, describe, expect, it } from "vitest";

import { useLayoutStore } from "@/stores/layoutStore";

describe("layoutStore", () => {
  beforeEach(() => {
    useLayoutStore.setState({
      sidebarCollapsed: false,
      mobileMenuOpen: false,
    });
  });

  it("toggles sidebar collapsed state", () => {
    useLayoutStore.getState().toggleSidebar();
    expect(useLayoutStore.getState().sidebarCollapsed).toBe(true);
    useLayoutStore.getState().toggleSidebar();
    expect(useLayoutStore.getState().sidebarCollapsed).toBe(false);
  });

  it("opens and closes mobile menu", () => {
    useLayoutStore.getState().setMobileMenuOpen(true);
    expect(useLayoutStore.getState().mobileMenuOpen).toBe(true);
    useLayoutStore.getState().setMobileMenuOpen(false);
    expect(useLayoutStore.getState().mobileMenuOpen).toBe(false);
  });
});
