import { describe, expect, it } from "vitest";

import {
  ENTRY_FUNNEL_STEPS,
  PORTFOLIO_POLICY_CONFIRM_TEXT,
  formatMinutesFromSeconds,
  validatePolicyFormValues,
} from "@/features/admin/upbit/upbitPortfolioPolicyHelpers";

describe("upbitPortfolioPolicyHelpers", () => {
  it("validates MA window order", () => {
    expect(
      validatePolicyFormValues({
        short_ma_window: 10,
        long_ma_window: 5,
      }),
    ).toContain("단기 MA");
    expect(
      validatePolicyFormValues({
        short_ma_window: 5,
        long_ma_window: 20,
        max_positions: 5,
      }),
    ).toBeNull();
  });

  it("formats wait minutes", () => {
    expect(formatMinutesFromSeconds(10800)).toBe("3시간");
    expect(formatMinutesFromSeconds(1800)).toBe("30분");
  });

  it("confirm text mentions no forced orders", () => {
    expect(PORTFOLIO_POLICY_CONFIRM_TEXT).toContain("강제 주문");
  });

  it("entry funnel includes MA steps", () => {
    expect(ENTRY_FUNNEL_STEPS.join(" ")).toMatch(/MA/);
    expect(ENTRY_FUNNEL_STEPS.length).toBeGreaterThanOrEqual(5);
  });
});

describe("UpbitPortfolioPolicyPanel wiring", () => {
  it("workspace imports policy panel and entry tab label", () => {
    const fs = require("node:fs");
    const path = require("node:path");
    const ws = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/upbit/UpbitAutotradingSettingsWorkspace.tsx",
      ),
      "utf8",
    );
    const cfg = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/upbit/upbitAutotradingSettingsConfig.ts",
      ),
      "utf8",
    );
    expect(ws).toContain("UpbitPortfolioPolicyPanel");
    expect(ws).toContain("설정 저장");
    expect(cfg).toContain("진입 · 후보 정책");
  });
});
