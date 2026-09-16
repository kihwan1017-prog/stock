/**
 * 연구 요약 카드 + 연구 워크스페이스 라우트 계약.
 */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

vi.mock("@/features/admin/api/adminApi", () => ({
  getAdminUbaResearchCollectionStatus: vi.fn(async () => ({
    overall_status: "COLLECTING",
    overall_status_ko: "수집 중",
    clean_forward: {
      count: 37,
      target_primary: 500,
      today_new: 2,
    },
  })),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/admin/research",
  useSearchParams: () => new URLSearchParams("market=UPBIT"),
}));

import { UpbitResearchCollectionSummaryCard } from "@/features/admin/upbit/UpbitResearchCollectionSummaryCard";

describe("strategy analysis research workspace", () => {
  it("summary card links to research with UPBIT market", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const html = renderToStaticMarkup(
      React.createElement(
        QueryClientProvider,
        { client: qc },
        React.createElement(UpbitResearchCollectionSummaryCard, { ubaId: 1380 }),
      ),
    );
    expect(html).toContain("연구 데이터");
    expect(html).toContain("전략·분석에서 자세히 보기");
    expect(html).toContain("market=UPBIT");
  });

  it("research page exists and reuses status panel", async () => {
    const page = readFileSync(
      join(process.cwd(), "src/app/(admin)/admin/research/page.tsx"),
      "utf8",
    );
    expect(page).toContain("UpbitResearchCollectionStatusPanel");
    expect(page).toContain("StrategyAnalysisToolbar");
    expect(page).toContain("키움 연구");
    expect(page).not.toContain("message=");
    expect(page).not.toContain("valueStyle");
  });

  it("menu hubs have page files", async () => {
    for (const route of [
      "research",
      "market-analysis",
      "ai-analysis",
      "strategy-validation",
      "strategy-candidates",
      "news-disclosures",
    ]) {
      const p = join(
        process.cwd(),
        `src/app/(admin)/admin/${route}/page.tsx`,
      );
      expect(existsSync(p), p).toBe(true);
    }
  });
});
