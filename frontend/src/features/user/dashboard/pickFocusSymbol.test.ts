import { describe, expect, it } from "vitest";

import { pickFocusSymbol } from "./pickFocusSymbol";

describe("STEP42 pickFocusSymbol", () => {
  it("AI 추천 1위를 우선한다", () => {
    expect(
      pickFocusSymbol([{ symbol: "000660" }], [{ symbol: "005930" }]),
    ).toBe("000660");
  });

  it("AI가 없으면 보유 1위를 사용한다", () => {
    expect(pickFocusSymbol([], [{ symbol: "035420" }])).toBe("035420");
  });

  it("둘 다 없으면 fallback", () => {
    expect(pickFocusSymbol([], [])).toBe("005930");
  });
});
