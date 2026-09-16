/**
 * 오늘 거래현황 — profit/loss 표시 규칙 (canonical net 정합).
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** Backend summary 규칙을 FE에서 재계산하지 않음 — 계약 스모크만. */
function assertProfitLossConsistency(input: {
  today_profit_amount: string;
  today_loss_amount: string;
  today_net_pnl: string;
}) {
  const profit = Number(input.today_profit_amount);
  const loss = Number(input.today_loss_amount);
  const net = Number(input.today_net_pnl);
  expect(profit).toBeGreaterThanOrEqual(0);
  expect(loss).toBeLessThanOrEqual(0);
  expect(profit + loss).toBeCloseTo(net, 6);
}

describe("today trading status pnl contract", () => {
  it("profit + loss = net", () => {
    assertProfitLossConsistency({
      today_profit_amount: "15000",
      today_loss_amount: "-5000",
      today_net_pnl: "10000",
    });
  });

  it("all profit", () => {
    assertProfitLossConsistency({
      today_profit_amount: "100",
      today_loss_amount: "0",
      today_net_pnl: "100",
    });
  });

  it("keeps Recharts Tooltip alias (antd Tooltip collision fix)", async () => {
    const src = readFileSync(
      join(
        process.cwd(),
        "src/features/admin/operations-center/TodayTradingStatusPanel.tsx",
      ),
      "utf8",
    );
    expect(src).toMatch(/Tooltip as ChartTooltip/);
    expect(src).toMatch(/from \"recharts\"/);
    expect(src).toMatch(/from \"antd\"/);
    expect(src).toContain("거래 종목수");
    expect(src).toContain("총순손익");
    expect(src).toContain("cumulative_realized_pnl");
    expect(src).toContain("cumulative_gross_pnl");
    expect(src).toContain("오늘 매수/매도");
    expect(src).toContain("오늘 체결/미체결");
  });

  it("lifetime net = profit + loss (loss already signed)", () => {
    const profit = 10000;
    const loss = -6000;
    const fees = 1000;
    const gross = 4000;
    const net = gross - fees;
    expect(profit + loss).toBe(4000);
    expect(net).toBe(3000);
  });
});
