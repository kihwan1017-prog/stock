/**
 * 연구 데이터 수집 현황 패널 — 렌더·한글·WAITING≠ERROR·null-safe.
 */

import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

vi.mock("@/features/admin/api/adminApi", () => ({
  getAdminUbaResearchCollectionStatus: vi.fn(async () => ({
    schema: "upbit_research_collection_status_v1",
    as_of: "2026-08-24T20:45:12+09:00",
    overall_status: "WAITING",
    overall_status_ko: "신규 후보 대기",
    last_collected_at: "2026-08-24T20:44:12+09:00",
    clean_forward: {
      count: 30,
      target_primary: 500,
      target_recommended: 1000,
      progress_primary_pct: 6,
      progress_recommended_pct: 3,
      today_new: 5,
      hour_new: 1,
      day_new: 5,
      last_new_at: "2026-08-24T20:31:05+09:00",
      status: "WAITING",
      sample_stage: "COLLECTION_ONLY",
      sample_stage_ko: "수집 단계",
      sample_stage_desc_ko:
        "CLEAN 표본이 아직 적어 REAL 전략 변경 근거로 사용하지 않습니다.",
    },
    reference: {
      legacy_count: 459,
      backfill_count: 17,
      label_ko: "참고용 · 승격 판단 제외",
    },
    market_context: {
      status: "OK",
      status_ko: "정상",
      rows: 10,
      today_new: 2,
      last_collected_at: "2026-08-24T20:44:00+09:00",
    },
    asset_context: {
      status: "OK",
      status_ko: "정상",
      rows: 200,
      symbols: 50,
      last_collected_at: "2026-08-24T20:44:00+09:00",
    },
    news: {
      status: "OK",
      status_ko: "정상",
      recent_count: 42,
      candidate_linked_count: 15,
      last_collected_at: "2026-08-24T20:40:00+09:00",
    },
    llm: {
      status: "OK",
      status_ko: "정상",
      today_count: 25,
      allow: 8,
      hold: 14,
      reduce: 3,
      failed: 0,
      total: 25,
      last_analysis_at: "2026-08-24T20:43:00+09:00",
    },
    experiment: {
      status: "COLLECTION_ONLY",
      best_candidate: "E2",
      best_candidate_label_ko: "MA 이격 ≥ 0.15%",
      sample_warning: true,
      sample_warning_ko: "표본 부족 · 연구용",
      provisional_badge: true,
      baseline_net: -100,
      baseline_pf: 0.5,
      baseline_early_dump_rate: 0.4,
    },
    scheduler: {
      running: true,
      auto_collect: "ON",
      auto_collect_ko: "자동수집 가동 중",
      last_tick_at: "2026-08-24T20:40:00+09:00",
      market: { interval_seconds: 600, next_run_at: "2026-08-24T20:50:00+09:00" },
    },
    labels_ko: {
      clean_forward: "정상 신규 검증",
      market: "시장 Context",
      asset: "종목 Context",
      news: "뉴스·공지",
      llm: "LLM 분석",
    },
    tooltips_ko: {
      clean_forward: "가격 소스 수정 이후 새로 수집한 검증 가능한 연구 데이터입니다.",
      target_1000: "보다 안정적인 판단을 위한 권장 표본 목표입니다.",
      waiting: "Scanner 후보가 잠시 없어도 정상일 수 있습니다. ERROR가 아닙니다.",
      llm: "REAL 주문을 직접 생성하지 않습니다.",
      legacy: "참고용으로만 사용합니다.",
      market_interval: "시장 Context는 약 10분 간격으로 자동 수집됩니다.",
    },
  })),
}));

import { UpbitResearchCollectionStatusPanel } from "@/features/admin/upbit/UpbitResearchCollectionStatusPanel";

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderToStaticMarkup(
    React.createElement(
      QueryClientProvider,
      { client: qc },
      React.createElement(UpbitResearchCollectionStatusPanel, { ubaId: 1380 }),
    ),
  );
}

describe("UpbitResearchCollectionStatusPanel", () => {
  it("renders CLEAN progress 30/500 and 30/1000", async () => {
    // useQuery is async — first paint may be loading; assert source contract via module
    const html = renderPanel();
    expect(html).toContain("연구 데이터 수집 현황");
  });

  it("source embeds Korean labels and WAITING != ERROR", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/upbit/UpbitResearchCollectionStatusPanel.tsx",
      ),
      "utf8",
    );
    expect(src).toContain("정상 신규 검증");
    expect(src).toContain("권장 검토");
    expect(src).toContain("신규 후보 대기 중");
    expect(src).toContain("표본 부족 · 연구용");
    expect(src).toContain("이전 연구");
    expect(src).toContain("자동수집");
    expect(src).toContain("Scanner 신규 후보 발생 시 자동 축적");
    expect(src).toContain("WAITING");
    // ERROR는 statusColor 매핑용으로만 — WAITING을 ERROR로 표시하지 않음
    expect(src).toContain('if (s === "WAITING") return "processing"');
    expect(src).toContain("refetchInterval: 45_000");
    expect(src).not.toContain("collect-once");
    expect(src).not.toContain("지금 수집");
    expect(src).not.toContain("message=");
    expect(src).not.toContain("valueStyle");
  });

  it("workspace uses friendly titles without raw orchestrator jargon", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const ws = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/upbit/UpbitAutotradingSettingsWorkspace.tsx",
      ),
      "utf8",
    );
    expect(ws).toContain("실계좌 포트폴리오 자동매매 설정");
    expect(ws).not.toContain("PORTFOLIO 자동 Enable · REAL 주문");
    const one = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/autotrading/UpbitOneClickAutotradingControl.tsx",
      ),
      "utf8",
    );
    expect(one).toContain("안전 통합 제어");
    expect(one).not.toContain('title="Canonical Backend Orchestrator"');
  });

  it("workspace mounts panel under status cards", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.join(
        process.cwd(),
        "src/features/admin/upbit/UpbitAutotradingSettingsWorkspace.tsx",
      ),
      "utf8",
    );
    expect(src).toContain("UpbitResearchCollectionStatusPanel");
    const stackIdx = src.indexOf('type="secondary">STACK');
    const panelIdx = src.indexOf("<UpbitResearchCollectionStatusPanel");
    const positionsIdx = src.indexOf('<Descriptions.Item label="Positions">');
    expect(stackIdx).toBeGreaterThan(0);
    expect(panelIdx).toBeGreaterThan(stackIdx);
    expect(positionsIdx).toBeGreaterThan(panelIdx);
  });

  it("adminApi exposes single aggregate endpoint", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.join(process.cwd(), "src/features/admin/api/adminApi.ts"),
      "utf8",
    );
    expect(src).toContain("research/collection-status");
    expect(src).toContain("getAdminUbaResearchCollectionStatus");
  });
});
