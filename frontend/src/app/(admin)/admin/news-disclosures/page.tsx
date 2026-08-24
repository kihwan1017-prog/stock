"use client";

/**
 * 전략·분석 → 뉴스·공시 허브.
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
        purposeKo="뉴스·공시를 시장 뱃지 기준으로 분리해 봅니다."
      />

      <MarketSection market={market} forMarket="KIWOOM" title="키움 뉴스·공시">
        <Space orientation="vertical" size={4}>
          <Link href={withMarketQuery(adminRoutes.news, "KIWOOM")}>뉴스</Link>
          <Link href={withMarketQuery(adminRoutes.disclosures, "KIWOOM")}>
            DART·기업 공시
          </Link>
        </Space>
      </MarketSection>

      <MarketSection market={market} forMarket="UPBIT" title="업비트 뉴스·공지">
        <Space orientation="vertical" size={4}>
          <Typography.Text>
            암호화폐 뉴스 · 업비트 공지 · 종목 연결
          </Typography.Text>
          <Link href={withMarketQuery(adminRoutes.researchData, "UPBIT")}>
            연구 데이터 (뉴스 수집 현황)
          </Link>
          <Link href={withMarketQuery(adminRoutes.news, "UPBIT")}>
            뉴스 관리 (exchange 필터)
          </Link>
        </Space>
      </MarketSection>
    </Space>
  );
}

export default function AdminNewsDisclosureHubPage() {
  return (
    <AdminPageShell
      title="뉴스·공시"
      description="키움 공시 · 업비트 공지/뉴스 (LLM 입력 여부는 연구 데이터에서 확인)"
    >
      <Suspense fallback={<Card size="small" loading />}>
        <Body />
      </Suspense>
    </AdminPageShell>
  );
}
