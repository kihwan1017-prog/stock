import { describe, expect, it } from "vitest";

import { adminMenuItems, flattenMenuItems } from "@/config/menu";
import { adminRoutes } from "@/config/routes";
import { friendlyReasonKo } from "@/features/admin/market-analysis/userFriendlyReasons";

describe("market data menu + analysis", () => {
  it("전략·분석에 시장 데이터 leaf 노출", () => {
    const grp = adminMenuItems.find((i) => i.key === "strategy-analysis");
    const keys = grp?.children?.map((c) => c.key) ?? [];
    expect(keys).toEqual(
      expect.arrayContaining([
        "strategies",
        "market-analysis",
        "market-data",
        "news-disclosures",
        "llm-learning",
      ]),
    );
    const md = grp?.children?.find((c) => c.key === "market-data");
    expect(md?.path).toBe(adminRoutes.marketData);
    expect(md?.label).toBe("시장 데이터");
  });

  it("시장 분석 matchPaths에 market-data 미포함 (독립 선택)", () => {
    const ma = flattenMenuItems(adminMenuItems).find(
      (i) => i.key === "market-analysis",
    );
    expect(ma?.matchPaths ?? []).not.toContain(adminRoutes.marketData);
  });

  it("user-friendly reason mapping", () => {
    expect(friendlyReasonKo("MARKET_CLOSED")).toContain("장 마감");
    expect(friendlyReasonKo("FEED_DOWN")).toContain("시세");
    expect(friendlyReasonKo("SHORT_MA_NOT_ABOVE_LONG_MA")).toContain("이동평균");
  });
});
