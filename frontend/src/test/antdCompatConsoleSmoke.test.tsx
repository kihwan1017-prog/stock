/**
 * Ant Design compatibility console smoke — Research panel + Alert title.
 */

import { describe, expect, it, vi, afterEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import {
  assertNoAntdConsoleNoise,
  startConsoleCapture,
} from "@/test/consoleSmoke";

vi.mock("@/features/admin/api/adminApi", () => ({
  getAdminUbaResearchCollectionStatus: vi.fn(async () => ({
    schema: "upbit_research_collection_status_v1",
    overall_status: "COLLECTING",
    overall_status_ko: "수집 중",
    last_collected_at: "2026-08-24T20:44:12+09:00",
    clean_forward: {
      count: 30,
      target_primary: 500,
      target_recommended: 1000,
      progress_primary_pct: 6,
      progress_recommended_pct: 3,
      today_new: 5,
      status: "WAITING",
      sample_stage_ko: "수집 단계",
      sample_stage_desc_ko: "연구용",
      last_new_at: "2026-08-24T20:31:05+09:00",
    },
    reference: { legacy_count: 459, backfill_count: 17, label_ko: "참고용" },
    market_context: { status: "OK", status_ko: "정상", rows: 10 },
    asset_context: { status: "OK", status_ko: "정상", rows: 200, symbols: 50 },
    news: { status: "OK", status_ko: "정상", recent_count: 16 },
    llm: { status: "WAITING", status_ko: "대기", today_count: 0 },
    experiment: {
      sample_warning: true,
      sample_warning_ko: "표본 부족 · 연구용",
      best_candidate_label_ko: "MA 이격",
      provisional_badge: true,
    },
    labels_ko: { clean_forward: "정상 신규 검증" },
    tooltips_ko: {},
  })),
}));

import { UpbitResearchCollectionStatusPanel } from "@/features/admin/upbit/UpbitResearchCollectionStatusPanel";

describe("antd compatibility console smoke", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("ResearchCollectionStatusPanel has no Alert message or Statistic valueStyle", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/upbit/UpbitResearchCollectionStatusPanel.tsx",
      ),
      "utf8",
    );
    expect(src).not.toMatch(/<Alert\b[\s\S]{0,120}?\bmessage=/);
    expect(src).toMatch(/<Alert\b[\s\S]{0,120}?\btitle=/);
    expect(src).not.toMatch(/<Statistic\b[\s\S]{0,200}?\bvalueStyle=/);
    expect(src).toMatch(/styles=\{\{\s*content:/);
  });

  it("static render does not emit forbidden console patterns", () => {
    const capture = startConsoleCapture();
    try {
      const qc = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const html = renderToStaticMarkup(
        React.createElement(
          QueryClientProvider,
          { client: qc },
          React.createElement(UpbitResearchCollectionStatusPanel, {
            ubaId: 1380,
          }),
        ),
      );
      expect(html).toContain("연구 데이터 수집 현황");
      assertNoAntdConsoleNoise(capture);
    } finally {
      capture.restore();
    }
  });

  it("repo has zero Alert message= and Statistic valueStyle= under src", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    function walk(dir: string, out: string[] = []): string[] {
      for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
        if (ent.name === "node_modules" || ent.name === ".next") continue;
        const p = path.join(dir, ent.name);
        if (ent.isDirectory()) walk(p, out);
        else if (ent.name.endsWith(".tsx")) out.push(p);
      }
      return out;
    }
    const files = walk(path.join(process.cwd(), "src"));
    const alertOffenders: string[] = [];
    const statisticOffenders: string[] = [];
    for (const file of files) {
      const text = fs.readFileSync(file, "utf8");
      for (const b of text.match(/<Alert\b[\s\S]*?>/g) || []) {
        if (/\bmessage=/.test(b)) alertOffenders.push(file);
      }
      for (const b of text.match(/<Statistic\b[\s\S]*?>/g) || []) {
        if (/\bvalueStyle=/.test(b)) statisticOffenders.push(file);
      }
    }
    expect(alertOffenders).toEqual([]);
    expect(statisticOffenders).toEqual([]);
  });
});
