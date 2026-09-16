import { describe, expect, it } from "vitest";

import { googleLoginStartUrl } from "@/features/auth/api/authApi";

describe("googleLoginStartUrl", () => {
  it("builds same-origin google login path", () => {
    const url = googleLoginStartUrl("/admin/dashboard");
    expect(url).toContain("/auth/google/login");
    expect(url).toContain("next=");
  });

  it("omits unsafe next", () => {
    const url = googleLoginStartUrl("https://evil.example");
    expect(url).not.toContain("next=");
  });
});
