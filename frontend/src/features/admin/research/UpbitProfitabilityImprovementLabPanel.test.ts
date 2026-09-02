import { describe, expect, it } from "vitest";

import { formatNumResearch } from "@/features/admin/upbit/researchDetailFormat";

describe("UpbitProfitabilityImprovementLabPanel helpers", () => {
  it("null-safe numeric format", () => {
    expect(formatNumResearch(null)).toBeTruthy();
    expect(formatNumResearch(undefined as unknown as null)).toBeTruthy();
  });
});
