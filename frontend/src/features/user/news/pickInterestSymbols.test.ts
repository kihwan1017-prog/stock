import { describe, expect, it } from "vitest";

import { pickInterestSymbols } from "./pickInterestSymbols";

describe("pickInterestSymbols", () => {
  it("중복·빈값을 제거하고 상한까지 반환한다", () => {
    expect(
      pickInterestSymbols(
        [
          { symbol: "005930" },
          { symbol: "005930" },
          { symbol: " " },
          { symbol: "000660" },
          { symbol: "035420" },
        ],
        2,
      ),
    ).toEqual(["005930", "000660"]);
  });

  it("포지션이 없으면 빈 배열", () => {
    expect(pickInterestSymbols([])).toEqual([]);
  });
});
