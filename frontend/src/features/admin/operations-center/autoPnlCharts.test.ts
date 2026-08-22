import { describe, expect, it } from "vitest";

import { AutoPnlCharts } from "@/features/admin/operations-center/AutoPnlCharts";

describe("AutoPnlCharts empty contract", () => {
  it("exports chart component for cockpit", () => {
    expect(typeof AutoPnlCharts).toBe("function");
  });
});
