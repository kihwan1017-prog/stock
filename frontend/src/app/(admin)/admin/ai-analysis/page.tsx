"use client";

/**
 * 전략·분석 → AI 분석 (결과 조회).
 * AI 설정(Provider/Prompt/Policy)과 분리.
 * UPBIT: Dual LLM (ANALYSIS + TRADING SHADOW) 패널.
 */

import { Card, Space, Typography } from "antd";
import Link from "next/link";
import { Suspense } from "react";

import { adminRoutes } from "@/config/routes";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import {
  MarketSection,
  StrategyAnalysisToolbar,
} from "@/features/admin/strategy-analysis/StrategyAnalysisToolbar";
import { withMarketQuery } from "@/features/admin/strategy-analysis/marketScope";
import { useStrategyMarketFromUrl } from "@/features/admin/strategy-analysis/MarketSelector";
import { UpbitDualLlmPanel } from "@/features/admin/upbit/UpbitDualLlmPanel";
import { KiwoomDualLlmPanel } from "@/features/admin/upbit/KiwoomDualLlmPanel";

function Body() {
  const market = useStrategyMarketFromUrl();
  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <StrategyAnalysisToolbar
        market={market}
        purposeKo="AI 분석 결과만 조회합니다. Provider/Prompt 설정은 AI 설정 메뉴를 사용하세요."
      />

      <MarketSection market={market} forMarket="KIWOOM" title="키움 Dual LLM">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          ANALYSIS(qwen3:1.7b) + TRADING SHADOW(qwen3.5:2b) + Teacher(qwen3.5:4b).
          MA REAL 경로와 분리 · UPBIT RAG 미혼합.
        </Typography.Paragraph>
        <KiwoomDualLlmPanel />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
          <Link href={withMarketQuery(adminRoutes.researchData, "KIWOOM")}>
            연구 데이터 → RAG / Feedback
          </Link>
        </Typography.Paragraph>
        <Space orientation="vertical" size={4} style={{ marginTop: 8 }}>
          <Link
            href={withMarketQuery(adminRoutes.aiMarketAnalyses, "KIWOOM")}
          >
            시장·차트 분석 결과
          </Link>
          <Link
            href={withMarketQuery(adminRoutes.aiCandidateAssessments, "KIWOOM")}
          >
            후보 평가 초안
          </Link>
        </Space>
      </MarketSection>

      <MarketSection market={market} forMarket="UPBIT" title="업비트 Dual LLM">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          ANALYSIS_LLM(qwen3:1.7b) + TRADING_LLM SHADOW(qwen3.5:2b). REAL
          주문·LIVE/ARM과 분리됩니다.
        </Typography.Paragraph>
        <UpbitDualLlmPanel />
        <Typography.Paragraph type="secondary" style={{ marginTop: 12 }}>
          <Link href={withMarketQuery(adminRoutes.researchData, "UPBIT")}>
            연구 데이터 → CLEAN / Context 상세
          </Link>
        </Typography.Paragraph>
      </MarketSection>

      <Card size="small" title="AI 설정으로 이동">
        <Link href={adminRoutes.aiProviders}>
          Provider · Prompt · Policy · Schema
        </Link>
      </Card>
    </Space>
  );
}

export default function AdminAiAnalysisHubPage() {
  return (
    <AdminPageShell
      title="AI 분석"
      description="분석 결과 조회 — Dual LLM SHADOW · 설정과 분리 · 주문 지시 아님"
    >
      <Suspense fallback={<Card size="small" loading />}>
        <Body />
      </Suspense>
    </AdminPageShell>
  );
}
