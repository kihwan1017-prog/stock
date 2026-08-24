"use client";

/**
 * 전략·분석 → 시장 분석 허브.
 * 기존 업비트 시세·지표·AI 시장분석 화면을 재사용(링크), 중복 API 없음.
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
        purposeKo="시장 상태·컨텍스트를 시장별로 확인합니다. DataLab 차단 소스는 AVAILABLE로 가장하지 않습니다."
      />

      <MarketSection market={market} forMarket="KIWOOM" title="키움 시장 분석">
        <Space orientation="vertical" size={4}>
          <Typography.Text>
            KRX 시장 상태 · 기술지표 · 시장 컨텍스트
          </Typography.Text>
          <Link href={withMarketQuery(adminRoutes.indicators, "KIWOOM")}>
            기술지표 관리
          </Link>
          <Link
            href={withMarketQuery(adminRoutes.aiMarketAnalyses, "KIWOOM")}
          >
            AI 시장·차트 분석 (참고용)
          </Link>
        </Space>
      </MarketSection>

      <MarketSection market={market} forMarket="UPBIT" title="업비트 시장 분석">
        <Space orientation="vertical" size={4}>
          <Typography.Text>
            Fear &amp; Greed · 상승 종목 비율 · 거래대금 · Asset Context
          </Typography.Text>
          <Link href={withMarketQuery(adminRoutes.upbitMarkets, "UPBIT")}>
            업비트 시세·종목
          </Link>
          <Link href={withMarketQuery(adminRoutes.researchData, "UPBIT")}>
            연구 데이터 (시장·종목 Context 포함)
          </Link>
          <Typography.Text type="secondary">
            DataLab 지수/알트시즌 등은 차단·보류 상태이며 정상 수집으로 표시하지
            않습니다.
          </Typography.Text>
        </Space>
      </MarketSection>
    </Space>
  );
}

export default function AdminMarketAnalysisHubPage() {
  return (
    <AdminPageShell
      title="시장 분석"
      description="키움·업비트 시장 컨텍스트 (자동매매 운영과 분리)"
    >
      <Suspense fallback={<Card size="small" loading />}>
        <Body />
      </Suspense>
    </AdminPageShell>
  );
}
