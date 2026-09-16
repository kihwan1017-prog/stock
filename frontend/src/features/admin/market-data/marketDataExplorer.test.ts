import { describe, expect, it } from "vitest";

import { adminRoutes } from "@/config/routes";

describe("market data explorer routes", () => {
  it("registers /admin/market-data", () => {
    expect(adminRoutes.marketData).toBe("/admin/market-data");
  });
});
