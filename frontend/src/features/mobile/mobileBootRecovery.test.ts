import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  MOBILE_BOOT_RECOVERY_KEY,
  hasBootRecoveryAttempted,
  isChunkLoadFailureMessage,
  markBootRecoveryAttempted,
} from "@/features/mobile/mobileBootRecovery";

describe("mobileBootRecovery", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("detects chunk load failure messages", () => {
    expect(isChunkLoadFailureMessage("ChunkLoadError: Loading chunk 123 failed")).toBe(
      true,
    );
    expect(
      isChunkLoadFailureMessage(
        "Failed to fetch dynamically imported module: /_next/static/chunks/x.js",
      ),
    ).toBe(true);
    expect(isChunkLoadFailureMessage("NetworkError when attempting to fetch")).toBe(
      false,
    );
  });

  it("guards recovery to a single attempt per session", () => {
    expect(hasBootRecoveryAttempted()).toBe(false);
    markBootRecoveryAttempted();
    expect(sessionStorage.getItem(MOBILE_BOOT_RECOVERY_KEY)).toBe("1");
    expect(hasBootRecoveryAttempted()).toBe(true);
  });
});
