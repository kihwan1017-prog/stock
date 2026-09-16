import { describe, expect, it } from "vitest";

import { maskEmailPreview, shouldHideTokenFromUi } from "@/features/user/profile/profileHelpers";

describe("STEP73 profile helpers", () => {
  it("masks email for display fallback", () => {
    expect(maskEmailPreview("kihwan@example.com")).toContain("***");
    expect(maskEmailPreview("kihwan@example.com")).not.toBe(
      "kihwan@example.com",
    );
  });

  it("never treats raw tokens as displayable profile fields", () => {
    expect(shouldHideTokenFromUi("accessToken")).toBe(true);
    expect(shouldHideTokenFromUi("refresh_token")).toBe(true);
    expect(shouldHideTokenFromUi("display_name")).toBe(false);
  });
});
