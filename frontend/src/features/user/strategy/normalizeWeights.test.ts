import { describe, expect, it } from "vitest";

import { normalizeWeights } from "./normalizeWeights";

describe("STEP46 normalizeWeights", () => {
  it("합을 1로 정규화한다", () => {
    expect(normalizeWeights([0.6, 0.4])).toEqual([0.6, 0.4]);
    const [a, b] = normalizeWeights([3, 1]);
    expect(a).toBeCloseTo(0.75);
    expect(b).toBeCloseTo(0.25);
  });

  it("합이 0이면 0", () => {
    expect(normalizeWeights([0, 0])).toEqual([0, 0]);
  });
});
