import { describe, expect, it } from "vitest";

import {
  kiwoomCrossStateLabelKo,
  kiwoomFreshCrossLabelKo,
  kiwoomModeTitleKo,
  kiwoomSignalStatusLabelKo,
  kiwoomWhyNoTradeLabelKo,
} from "@/features/admin/autotrading/kiwoomTop10Labels";

describe("kiwoomTop10Labels", () => {
  it("maps cross / fresh / why-no-trade to Korean without raw enums", () => {
    expect(kiwoomCrossStateLabelKo("FRESH_CROSS")).toBe("Fresh Cross 감지");
    expect(kiwoomFreshCrossLabelKo("FRESH_CROSS")).toBe("감지");
    expect(kiwoomFreshCrossLabelKo("BELOW")).toBe("대기");
    expect(kiwoomWhyNoTradeLabelKo("NO_FRESH_GOLDEN_CROSS")).toBe(
      "Fresh Golden Cross 미발생",
    );
    expect(kiwoomSignalStatusLabelKo("SHADOW_CANDIDATE")).toBe("Shadow 후보");
  });

  it("titles REAL mode clearly", () => {
    expect(kiwoomModeTitleKo("REAL", true)).toBe("TOP10 REAL 자동매매");
    expect(kiwoomModeTitleKo("SHADOW", false)).toBe("TOP10 SHADOW 관측");
  });
});
