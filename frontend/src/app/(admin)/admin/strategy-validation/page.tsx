"use client";

/**
 * 전략·분석 → 전략 검증 허브.
 * 기존 백테스트·포트폴리오 검증·업비트 CLEAN 실험 재사용.
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
        purposeKo="검증·실험 결과를 시장별로 확인합니다. Legacy/Backfill은 참고용입니다."
      />

      <MarketSection market={market} forMarket="KIWOOM" title="키움 전략 검증">
        <Space orientation="vertical" size={4}>
          <Link href={withMarketQuery(adminRoutes.backtests, "KIWOOM")}>
            백테스트
          </Link>
          <Link
            href={withMarketQuery(adminRoutes.portfolioValidations, "KIWOOM")}
          >
            포트폴리오 검증
          </Link>
          <Link
            href={withMarketQuery(adminRoutes.aiCandidatePromotions, "KIWOOM")}
          >
            후보 승격 근거
          </Link>
        </Space>
      </MarketSection>

      <MarketSection market={market} forMarket="UPBIT" title="업비트 전략 검증">
        <Space orientation="vertical" size={4}>
          <Typography.Text>
            정상 신규 검증(CLEAN) · Baseline · E1~E8 필터 · Early Dump · Shadow
            A/B
          </Typography.Text>
          <Link href={withMarketQuery(adminRoutes.researchData, "UPBIT")}>
            연구 데이터 (CLEAN · 필터 실험)
          </Link>
          <Typography.Text type="secondary">
            이전 연구(Legacy)·보완(Backfill)은 CLEAN과 합산하지 않습니다.
          </Typography.Text>
        </Space>
      </MarketSection>
    </Space>
  );
}

export default function AdminStrategyValidationHubPage() {
  return (
    <AdminPageShell
      title="전략 검증"
      description="백테스트·CLEAN·필터 실험 (승격 자동 적용 없음)"
    >
      <Suspense fallback={<Card size="small" loading />}>
        <Body />
      </Suspense>
    </AdminPageShell>
  );
}
