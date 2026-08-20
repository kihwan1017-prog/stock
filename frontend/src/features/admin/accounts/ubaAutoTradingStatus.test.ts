import { describe, expect, it } from "vitest";

import {
  buildUbaAutoTradingViewModel,
  recommendationBadgeColor,
} from "./ubaAutoTradingStatus";

describe("buildUbaAutoTradingViewModel", () => {
  it("maps BLOCKED + AI HOLD for current UBA 1380-like snapshot", () => {
    const vm = buildUbaAutoTradingViewModel({
      status: "BLOCKED",
      blockers: ["LIVE_OFF", "ARM_OFF_OR_EXPIRED"],
      warnings: ["AI_ANALYSIS_STALE_OR_MISSING"],
      runtime_status: "READY",
      checks: {
        strategy_links: {
          approved_active_count: 1,
          items: [
            {
              strategy_id: 17483,
              name: "UPBIT MA Crossover KRW-XRP",
              symbol: "KRW-XRP",
              is_active: true,
              strategy_is_active: true,
              approved: true,
            },
          ],
        },
        runtime: {
          status: "READY",
          matching: [
            {
              status: "PAUSED",
              deployment_id: 868,
              strategy_id: 17483,
              symbol: "KRW-XRP",
              broker_code: "UPBIT",
            },
          ],
        },
        market_feed: {
          ok: true,
          reason: "OK",
          age_seconds: 1.2,
          stale_limit_seconds: 30,
          symbols: ["KRW-XRP"],
          hub: { hub_status: "CONNECTED" },
          quote_ws: { connected: true, running: true },
          cache_hit: { trade_price: "1443.0", received_at: "2026-08-11T06:00:00+09:00" },
          last_received_at: "2026-08-11T06:00:00+09:00",
        },
        market_context: {
          latest_analysis: {
            market_analysis_id: 37,
            analysis_at: "2026-08-11T06:00:36+09:00",
            fresh: true,
            recommendation: "HOLD",
            confidence: 0.5,
            risk_level: "MEDIUM",
            provider: "ollama",
            model: "qwen3.5:4b",
            reasons: ["trend=UNCERTAIN"],
          },
          ai_analysis_job: {
            enabled: true,
            running: true,
            interval_seconds: 300,
            last_run_at: "2026-08-11T06:04:07+09:00",
            last_success_at: "2026-08-11T06:04:07+09:00",
            next_run_at: "2026-08-11T06:09:07+09:00",
            success_count: 2,
            failure_count: 0,
          },
        },
        ai_signal_gate: {
          enabled: true,
          paper_active: true,
          live_enabled: false,
          live_fail_closed: true,
          stale: false,
          latest: { recommendation: "HOLD", confidence: 0.5 },
        },
        risk: {
          resolved: true,
          kst_date: "2026-08-11",
          daily_order_count: 0,
          daily_order_limit: 1,
          max_order_amount: "5100.00",
          daily_max_order_amount: "30000",
          risk_counted_order_ids: [],
        },
        activation: {
          ok: true,
          transition_id: 5,
          activation_status: "ACTIVE",
          expires_at: "2026-08-11T09:42:25+09:00",
          remaining_ttl_seconds: 10000,
        },
        live: { live_order_enabled: false },
        arm: { armed: false, expires_at: null, expired: false },
        live_outbox_worker: { enabled: true, running: false },
        pending_live_outbox: 0,
        pipeline: { ops_ready: true, blockers: [] },
      },
    });

    expect(vm.headline).toBe("BLOCKED");
    expect(vm.finalLabel).toBe("BLOCKED");
    expect(vm.aiAnalysis.recommendation).toBe("HOLD");
    expect(vm.displayBlockers).not.toContain("AI HOLD");
    expect(vm.displayBlockers).toContain("LIVE OFF");
    expect(vm.displayBlockers).toContain("ARM OFF");
    expect(vm.strategy.strategyId).toBe("17483");
    expect(vm.strategy.runtimeStatus).toBe("READY");
    expect(vm.marketFeed.healthy).toBe(true);
    expect(vm.aiAnalysis.recommendation).toBe("HOLD");
    expect(vm.aiAnalysis.fresh).toBe(true);
    expect(vm.aiGate.liveOn).toBe(false);
    expect(vm.aiGate.assumedResult).toContain("LIVE_GATE_OFF");
    expect(vm.dailyRisk.dailyOrderCount).toBe("0");
    expect(vm.dailyRisk.dailyOrderLimit).toBe("1");
    expect(vm.ops.transitionId).toBe("5");
    expect(vm.ops.startAllForbidden).toBe(true);
    expect(vm.ops.runtimeLifecycle).toBe("READY");
    expect(vm.checklist.find((c) => c.label === "LIVE")?.result).toBe("BLOCK");
    expect(vm.checklist.find((c) => c.label === "Market Feed")?.result).toBe(
      "PASS",
    );
    expect(recommendationBadgeColor("HOLD")).toBe("orange");
  });

  it("maps READY_FOR_AUTO_TRADING to READY headline", () => {
    const vm = buildUbaAutoTradingViewModel({
      status: "READY_FOR_AUTO_TRADING",
      blockers: [],
      warnings: [],
      checks: {
        runtime: { status: "READY", matching: [] },
        strategy_links: { approved_active_count: 1, items: [] },
        market_feed: { ok: true, reason: "OK" },
        activation: { ok: true, activation_status: "ACTIVE" },
        live: { live_order_enabled: true },
        arm: { armed: true, expired: false },
        live_outbox_worker: { enabled: true, running: true },
        pending_live_outbox: 0,
        risk: { resolved: true },
        ai_signal_gate: { live_enabled: true, paper_active: true },
        market_context: {
          latest_analysis: { fresh: true, recommendation: "ALLOW" },
        },
        pipeline: { ops_ready: true, blockers: [] },
      },
    });
    expect(vm.headline).toBe("READY");
    expect(vm.finalLabel).toBe("READY_FOR_AUTO_TRADING");
    expect(vm.aiGate.assumedResult).toBe("AI_GATE_ALLOW");
  });
});
