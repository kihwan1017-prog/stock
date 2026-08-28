/**
 * Mobile read-only PWA — format + write-API absence.
 */

import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  formatKrwSigned,
  overallEmoji,
  sideKo,
} from "@/features/mobile/mobileFormat";
import { MobileHomeDashboard } from "@/features/mobile/MobileHomeDashboard";
import { queryKeys } from "@/lib/query/queryKeys";

describe("mobileFormat", () => {
  it("formats signed KRW", () => {
    expect(formatKrwSigned(1234)).toBe("+1,234원");
    expect(formatKrwSigned(-550)).toBe("-550원");
    expect(formatKrwSigned(0)).toBe("0원");
  });

  it("maps side and overall emoji", () => {
    expect(sideKo("BUY")).toBe("매수");
    expect(sideKo("SELL")).toBe("매도");
    expect(overallEmoji("HEALTHY")).toContain("🟢");
    expect(overallEmoji("STOPPED")).toContain("🔴");
  });
});

describe("mobile read-only guarantee", () => {
  it("mobile feature tree has no mutation API calls", () => {
    const root = path.join(process.cwd(), "src/features/mobile");
    const files = fs
      .readdirSync(root)
      .filter(
        (f) =>
          (f.endsWith(".ts") || f.endsWith(".tsx")) && !f.includes(".test."),
      );
    for (const f of files) {
      const src = fs.readFileSync(path.join(root, f), "utf8");
      expect(src).not.toMatch(/\b(postJson|putJson|patchJson|deleteJson)\b/);
      expect(src).not.toMatch(/apiClient\.(post|put|patch|delete)\s*\(/);
    }
  });

  it("renders overview cards from hydrated query data", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(queryKeys.mobile.overview(), {
      updated_at: "2026-08-26T00:00:00+09:00",
      overall: { status: "HEALTHY", label_hint: "정상 운영" },
      system: { status: "HEALTHY", kill_switch: false },
      upbit: {
        auto_trading_state: "RUNNING",
        live: true,
        arm: true,
        scanner: "RUNNING",
        feed: "REAL_FRESH",
        today_buy_count: 1,
        today_sell_count: 2,
        can_auto_trade: true,
      },
      kiwoom: {
        market_status: "CLOSED",
        auto_trading_state: "STOPPED",
        live: false,
        arm: false,
        runtime: "STOPPED",
        runner: "STOPPED",
        feed: "REAL_FRESH",
        today_buy_count: 0,
        today_sell_count: 0,
        can_auto_trade: false,
      },
      today: {
        realized_pnl: 1000,
        unrealized_pnl: -100,
        total_pnl: 900,
        by_broker: {
          UPBIT: { realized_pnl: 1000 },
          KIWOOM: { realized_pnl: 0 },
        },
      },
      positions: { count: 0, items: [] },
      recent_orders: [],
      recent_events: [],
      ai: {
        analysis_model: "qwen3:1.7b",
        trading_model: "qwen3.5:2b",
        teacher_model: "qwen3.5:4b",
        trading_mode: "SHADOW",
        clean_count: 37,
        clean_target: 500,
        rag_label: "수집 중",
      },
    });

    const html = renderToStaticMarkup(
      React.createElement(
        QueryClientProvider,
        { client: qc },
        React.createElement(MobileHomeDashboard),
      ),
    );
    expect(html).toContain("오늘 운영");
    expect(html).toContain("정상 운영");
    expect(html).toContain("UPBIT");
    expect(html).toContain("KIWOOM");
    expect(html).toContain("SHADOW");
    expect(html).toContain("qwen3:1.7b");
    expect(html).not.toMatch(/LIVE ON\/OFF|ARM 설정|주문 생성/);
  });
});
