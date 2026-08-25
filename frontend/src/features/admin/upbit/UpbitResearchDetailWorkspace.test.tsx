/**
 * Research detail format + workspace null-safety / Korean labels.
 */

import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import fs from "node:fs";
import path from "node:path";

import {
  dash,
  formatPctResearch,
  formatPriceResearch,
  safeArray,
} from "@/features/admin/upbit/researchDetailFormat";
import { upbitResearchDetailTabs } from "@/features/admin/upbit/UpbitResearchDetailWorkspace";
import { queryKeys } from "@/lib/query/queryKeys";

vi.mock("@/features/admin/api/adminApi", () => ({
  getAdminUpbitResearchCleanForward: vi.fn(async () => ({ items: [], total: 0 })),
  getAdminUpbitResearchCleanForwardDetail: vi.fn(async () => ({})),
  getAdminUpbitResearchMarketContext: vi.fn(async () => ({ items: [], total: 0 })),
  getAdminUpbitResearchAssetContext: vi.fn(async () => ({ items: [], total: 0 })),
  getAdminUpbitResearchNews: vi.fn(async () => ({ items: [], total: 0 })),
  getAdminUpbitResearchLlmAnalysis: vi.fn(async () => ({
    items: [],
    total: 0,
    empty_hint_ko: "신규 Scanner Shadow 후보 발생 시 분석됩니다.",
  })),
  getAdminUpbitResearchLlmAnalysisDetail: vi.fn(async () => ({})),
  getAdminUpbitResearchExperiments: vi.fn(async () => ({})),
}));

describe("researchDetailFormat", () => {
  it("null-safe dash and arrays", () => {
    expect(dash(null)).toBe("—");
    expect(dash(undefined)).toBe("—");
    expect(safeArray(null)).toEqual([]);
    expect(safeArray([{ a: 1 }])).toHaveLength(1);
  });

  it("formats price and pct without scientific notation", () => {
    expect(formatPriceResearch("0E-8")).toBe("0원");
    expect(formatPriceResearch(10780)).toContain("10,780");
    expect(formatPctResearch(1.2345)).toContain("%");
    expect(formatPctResearch(null)).toBe("—");
  });
});

describe("UpbitResearchDetailWorkspace", () => {
  it("renders CLEAN chrome without undefined/NaN", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const params = {
      page: 1,
      page_size: 20,
      symbol: undefined,
      recommendation: undefined,
      outcome: undefined,
      early_dump: undefined,
      data_quality: undefined,
    };
    qc.setQueryData(queryKeys.admin.upbitResearchCleanForward(params), {
      items: [
        {
          shadow_id: 1,
          detected_at: "2026-08-24T12:00:00+09:00",
          symbol: "KRW-BTC",
          scanner_run_id: "run1",
          candidate_score: 0.9,
          ai_recommendation: "ALLOW",
          ai_confidence: 0.8,
          canonical_entry_price: 100000000,
          entry_price_quality: "CANONICAL",
          return_5m_pct: 0.12,
          return_15m_pct: null,
          return_30m_pct: undefined,
          return_60m_pct: 0.01,
          mfe_pct: 0.5,
          mae_pct: -0.2,
          outcome_label: "WIN",
          early_dump: false,
          data_quality: "CANONICAL",
          is_clean: true,
        },
      ],
      total: 1,
      page: 1,
      page_size: 20,
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <upbitResearchDetailTabs.CleanForwardTab />
      </QueryClientProvider>,
    );
    expect(html).toContain("정상 신규 검증 표본");
    expect(html).toContain("CLEAN 총 1건");
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("NaN");
    expect(html).not.toMatch(/\bnull\b/);
  });

  it("hydrated experiments show sample warning and research-candidate", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(queryKeys.admin.upbitResearchExperiments(), {
      under_promotion_sample: true,
      warning_ko: "연구 표본 수집 중 — REAL 전략 승격 근거로 사용할 수 없습니다.",
      best_filter_currently: { code: "E3" },
      best_filter_label_ko: "현재 연구 후보",
      clean_sample_count: 37,
      sample_gate: "COLLECTION_ONLY",
      arms: [
        {
          experiment: "E0",
          name: "baseline",
          accepted: 37,
          filtered: 0,
          avoided_loss: 0,
          missed_winner: 0,
          benefit: 0,
          net: 0,
          pf: 1,
          early_dump_rate: 0.1,
        },
      ],
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <upbitResearchDetailTabs.ExperimentsTab />
      </QueryClientProvider>,
    );
    expect(html).toContain("연구 표본 수집 중");
    expect(html).toContain("현재 연구 후보");
    expect(html).not.toContain("추천 전략");
    expect(html).toContain("연구 후보 표시일 뿐");
  });

  it("hydrated LLM empty is not an error state", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(
      queryKeys.admin.upbitResearchLlmAnalysis({
        page: 1,
        page_size: 20,
      }),
      {
        items: [],
        total: 0,
        empty_hint_ko: "신규 Scanner Shadow 후보 발생 시 분석됩니다.",
      },
    );
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <upbitResearchDetailTabs.LlmTab />
      </QueryClientProvider>,
    );
    expect(html).toContain("신규 Scanner Shadow 후보 발생 시 분석됩니다.");
    expect(html).not.toContain("조회 실패");
  });

  it("source uses Drawer size (not deprecated width) and READ APIs", () => {
    const src = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/upbit/UpbitResearchDetailWorkspace.tsx",
      ),
      "utf8",
    );
    expect(src).not.toContain("message=");
    expect(src).not.toMatch(/\bvalueStyle\b/);
    expect(src).toContain('size="large"');
    expect(src).toContain("size={720}");
    // Drawer width prop 전수 금지 (antd 6 size로 대체)
    expect(src).not.toMatch(/<Drawer[\s\S]*?\bwidth=/);
    const api = fs.readFileSync(
      path.join(process.cwd(), "src/features/admin/api/adminApi.ts"),
      "utf8",
    );
    expect(api).toContain("/admin/upbit/research/clean-forward");
    expect(api).toContain("getAdminUpbitResearchExperiments");
  });
});
