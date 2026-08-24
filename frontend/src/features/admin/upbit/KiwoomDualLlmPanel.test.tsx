/**
 * Kiwoom Dual LLM panel — null-safe / SHADOW / no deprecated AntD.
 */

import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import fs from "node:fs";
import path from "node:path";

import { KiwoomDualLlmPanel } from "@/features/admin/upbit/KiwoomDualLlmPanel";
import { queryKeys } from "@/lib/query/queryKeys";

vi.mock("@/features/admin/api/adminApi", () => ({
  getAdminKiwoomDualLlmStatus: vi.fn(async () => ({})),
  getAdminKiwoomDualLlmRecent: vi.fn(async () => ({ items: [] })),
}));

describe("KiwoomDualLlmPanel", () => {
  it("renders SHADOW labels and market isolation note", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(queryKeys.admin.kiwoomDualLlmStatus(), {
      ANALYSIS_LLM_MODEL: "qwen3:1.7b",
      TRADING_LLM_MODEL: "qwen3.5:2b",
      TEACHER_LLM_MODEL: "qwen3.5:4b",
      TRADING_LLM_MODE: "SHADOW",
      SAMPLE_STAGE: "COLLECTION_ONLY",
      clean_sample_count: 0,
      dual_llm_rows_stored: 0,
      analysis: { calls: 0, ok: 0, median_latency_ms: null },
      trading_shadow: { calls: 0, ok: 0, mode: "SHADOW" },
      teacher: { calls: 0 },
      feedback_metrics: { ALLOW: 0, HOLD: 0, REDUCE: 0 },
      dataset: { GOLD: 0, SILVER: 0 },
    });
    qc.setQueryData(queryKeys.admin.kiwoomDualLlmRecent({ limit: 20 }), {
      items: [],
    });
    const html = renderToStaticMarkup(
      <QueryClientProvider client={qc}>
        <KiwoomDualLlmPanel />
      </QueryClientProvider>,
    );
    expect(html).toContain("KIWOOM");
    expect(html).toContain("SHADOW");
    expect(html).toContain("qwen3:1.7b");
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("NaN");
  });

  it("source avoids deprecated AntD props", () => {
    const src = fs.readFileSync(
      path.join(process.cwd(), "src/features/admin/upbit/KiwoomDualLlmPanel.tsx"),
      "utf8",
    );
    expect(src).not.toMatch(/\bvalueStyle\b/);
    expect(src).not.toContain("message=");
  });
});
