"use client";

/**
 * 전략·분석 → AI 분석 (결과 조회).
 * AI 설정(Provider/Prompt/Policy)과 분리.
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

function Body() {
  const market = useStrategyMarketFromUrl();
  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <StrategyAnalysisToolbar
        market={market}
        purposeKo="AI 분석 결과만 조회합니다. Provider/Prompt 설정은 AI 설정 메뉴를 사용하세요."
      />

      <MarketSection market={market} forMarket="KIWOOM" title="키움 AI 분석">
        <Space orientation="vertical" size={4}>
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
          <Link href={withMarketQuery(adminRoutes.aiReviews, "KIWOOM")}>
            분석 품질 검토
          </Link>
        </Space>
      </MarketSection>

      <MarketSection market={market} forMarket="UPBIT" title="업비트 AI 분석">
        <Space orientation="vertical" size={4}>
          <Typography.Text>
            LLM 시장·뉴스·종목 컨텍스트 분석 (후보 발생 시)
          </Typography.Text>
          <Link href={withMarketQuery(adminRoutes.researchData, "UPBIT")}>
            연구 데이터 → LLM / 수집 현황
          </Link>
          <Typography.Text type="secondary">
            추천(ALLOW/HOLD/REDUCE)은 연구용이며 REAL 주문을 만들지 않습니다.
          </Typography.Text>
        </Space>
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
      description="분석 결과 조회 — 설정과 분리 · 참고용(주문 지시 아님)"
    >
      <Suspense fallback={<Card size="small" loading />}>
        <Body />
      </Suspense>
    </AdminPageShell>
  );
}
