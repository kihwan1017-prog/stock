import { describe, expect, it } from "vitest";

import { classifyCheckpointLabel } from "./exitStrategyShadowLabels";

describe("exitStrategyShadowLabels", () => {
  it("maps checkpoint bands", () => {
    expect(classifyCheckpointLabel(0)).toBe("INSUFFICIENT");
    expect(classifyCheckpointLabel(30)).toBe("SANITY_ONLY");
    expect(classifyCheckpointLabel(50)).toBe("EARLY_SIGNAL");
    expect(classifyCheckpointLabel(100)).toBe("CANDIDATE");
    expect(classifyCheckpointLabel(200)).toBe("VALIDATION");
    expect(classifyCheckpointLabel(300)).toBe("PROMOTION_REVIEW_ELIGIBLE");
  });
});
