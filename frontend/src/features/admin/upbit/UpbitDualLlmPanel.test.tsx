/**
 * Dual LLM panel — null-safe / SHADOW labels / no deprecated AntD.
 */

import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import fs from "node:fs";
import path from "node:path";

import { UpbitDualLlmPanel } from "@/features/admin/upbit/UpbitDualLlmPanel";
import { queryKeys } from "@/lib/query/queryKeys";

vi.mock("@/features/admin/api/adminApi", () => ({
  getAdminUpbitDualLlmStatus: vi.fn(async () => ({})),
  getAdminUpbitDualLlmRecent: vi.fn(async () => ({ items: [] })),
  getAdminUpbitDualLlmComparison: vi.fn(async () => ({})),
  getAdminUpbitDualLlmRagFeedback: vi.fn(async () => ({ items: [] })),
  getAdminUpbitDualLlmRagFeedbackDetail: vi.fn(async () => ({})),
}));

describe("UpbitDualLlmPanel", () => {
  it("renders ANALYSIS and TRADING SHADOW cards from hydrated status", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(queryKeys.admin.upbitDualLlmStatus(), {
      ANALYSIS_LLM_MODEL: "qwen3:1.7b",
      TRADING_LLM_MODEL: "qwen3.5:2b",
      TEACHER_LLM_MODEL: "qwen3.5:4b",
      ANALYSIS_LLM_WIRED: true,
      TRADING_LLM_WIRED: true,
      TRADING_LLM_MODE: "SHADOW",
      REFERENCE_MODEL: "qwen3.5:4b",
      SAMPLE_STAGE: "COLLECTION_ONLY",
      clean_sample_count: 37,
      promotion_status: "COLLECTION_ONLY",
      promotion_status_ko: "수집 전용 — REAL 승격 근거 아님",
      dual_llm_rows_stored: 0,
      analysis: {
        calls: 0,
        ok: 0,
        timeouts: 0,
        errors: 0,
        cache_hits: 0,
        median_latency_ms: null,
      },
      trading_shadow: {
        calls: 0,
        ok: 0,
        timeouts: 0,
        errors: 0,
        median_latency_ms: null,
        mode: "SHADOW",
      },
      teacher: {
        calls: 0,
        ok: 0,
        review_rate: null,
      },
      feedback_metrics: {
        ALLOW: 0,
        HOLD: 0,
        REDUCE: 0,
      },
      rag: { hit_rate: 0, average_similar_cases: null },
      dataset: { GOLD: 0, SILVER: 0 },
    });
    qc.setQueryData(queryKeys.admin.upbitDualLlmRecent({ limit: 20 }), {
      items: [],
    });
    qc.setQueryData(queryKeys.admin.upbitDualLlmComparison(), {
      CURRENT_HEURISTIC_VS_LLM_SHADOW_AVAILABLE: false,
      dual_shadow_sample_count: 0,
    });

    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <UpbitDualLlmPanel />
      </QueryClientProvider>,
    );
    expect(html).toContain("분석 LLM");
    expect(html).toContain("qwen3:1.7b");
    expect(html).toContain("qwen3.5:2b");
    expect(html).toContain("SHADOW");
    expect(html).toContain("Teacher");
    expect(html).toContain("RAG / Feedback KPI");
    expect(html).toContain("연구·SHADOW 전용");
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("NaN");
  });

  it("source avoids deprecated AntD props and exposes dual-llm APIs", () => {
    const src = fs.readFileSync(
      path.join(process.cwd(), "src/features/admin/upbit/UpbitDualLlmPanel.tsx"),
      "utf8",
    );
    expect(src).not.toMatch(/\bvalueStyle\b/);
    expect(src).not.toContain("message=");
    const api = fs.readFileSync(
      path.join(process.cwd(), "src/features/admin/api/adminApi.ts"),
      "utf8",
    );
    expect(api).toContain("/admin/upbit/dual-llm/status");
    expect(api).toContain("getAdminUpbitDualLlmComparison");
    expect(api).toContain("getAdminUpbitDualLlmRagFeedback");
  });
});
