import { describe, expect, it } from "vitest";

import { computeMaxDrawdownPct } from "@/features/user/portfolio/mdd";

describe("STEP66 portfolio period helpers", () => {
  it("computes MDD percent from equity series", () => {
    // peak 120 → 90 = 25%
    expect(computeMaxDrawdownPct([100, 120, 90, 95, 110])).toBeCloseTo(
      25,
      5,
    );
  });

  it("returns 0 for empty or flat series", () => {
    expect(computeMaxDrawdownPct([])).toBe(0);
    expect(computeMaxDrawdownPct([100, 100, 100])).toBe(0);
  });
});
