"use client";

/**
 * 전략·분석 → 전략·후보 허브 (시장 선택 + 기존 화면 링크).
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
        purposeKo="후보·스캐너·승격 흐름을 시장별로 봅니다. 점수를 하나로 합산하지 않습니다."
      />

      <MarketSection market={market} forMarket="KIWOOM" title="키움 전략·후보">
        <Space orientation="vertical" size={4}>
          <Link href={withMarketQuery(adminRoutes.strategies, "KIWOOM")}>
            전략 정의·승인
          </Link>
          <Link
            href={withMarketQuery(adminRoutes.aiCandidateLifecycle, "KIWOOM")}
          >
            후보 Lifecycle
          </Link>
          <Link
            href={withMarketQuery(adminRoutes.aiCandidateAssessments, "KIWOOM")}
          >
            후보 평가
          </Link>
          <Link
            href={withMarketQuery(adminRoutes.strategyRequests, "KIWOOM")}
          >
            전략 요청
          </Link>
          <Link href={withMarketQuery(adminRoutes.strategyDrafts, "KIWOOM")}>
            전략 초안
          </Link>
        </Space>
      </MarketSection>

      <MarketSection market={market} forMarket="UPBIT" title="업비트 전략·후보">
        <Space orientation="vertical" size={4}>
          <Typography.Text>
            Opportunity Scanner · Shadow · CLEAN 후보 · AI 추천
          </Typography.Text>
          <Link href={withMarketQuery(adminRoutes.researchData, "UPBIT")}>
            연구 데이터 (Shadow / CLEAN)
          </Link>
          <Link href={adminRoutes.autotradingUpbit}>
            업비트 자동매매 (운영 — 후보 슬롯)
          </Link>
          <Typography.Text type="secondary">
            Scanner 점수와 키움 후보 점수는 별도입니다.
          </Typography.Text>
        </Space>
      </MarketSection>
    </Space>
  );
}

export default function AdminStrategyCandidatesHubPage() {
  return (
    <AdminPageShell
      title="전략·후보"
      description="키움·업비트 후보·전략 흐름 (운영 LIVE와 분리)"
    >
      <Suspense fallback={<Card size="small" loading />}>
        <Body />
      </Suspense>
    </AdminPageShell>
  );
}
