"use client";

/**
 * 전략·분석 → 연구 데이터 워크스페이스.
 * UPBIT: collection-status 패널 재사용. KIWOOM: 존재하는 연구 링크만.
 */

import { Alert, Card, Collapse, Space, Tabs, Typography } from "antd";
import Link from "next/link";
import { Suspense, useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { StrategyAnalysisToolbar } from "@/features/admin/strategy-analysis/StrategyAnalysisToolbar";
import {
  isKiwoomVisible,
  isUpbitVisible,
  withMarketQuery,
} from "@/features/admin/strategy-analysis/marketScope";
import { useStrategyMarketFromUrl } from "@/features/admin/strategy-analysis/MarketSelector";
import { UpbitResearchCollectionStatusPanel } from "@/features/admin/upbit/UpbitResearchCollectionStatusPanel";
import { DEFAULT_UPBIT_AUTOTRADING_UBA_ID } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";

function ResearchWorkspaceBody() {
  const market = useStrategyMarketFromUrl();
  const [ubaId] = useState(DEFAULT_UPBIT_AUTOTRADING_UBA_ID);
  const showKiwoom = isKiwoomVisible(market);
  const showUpbit = isUpbitVisible(market);

  const upbitTabs = useMemo(
    () => [
      {
        key: "status",
        label: "수집 현황",
        children: <UpbitResearchCollectionStatusPanel ubaId={ubaId} />,
      },
    ],
    [ubaId],
  );

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <StrategyAnalysisToolbar
        market={market}
        purposeKo="연구·검증용 데이터만 모읍니다. 실주문·LIVE/ARM과는 분리됩니다."
      />

      {market === "ALL" ? (
        <Alert
          type="warning"
          showIcon
          title="시장별로 따로 확인하세요"
          description="업비트 정상 신규 검증(CLEAN)과 키움 연구 데이터를 합산하지 않습니다."
        />
      ) : null}

      {showUpbit ? (
        <Card size="small" title="업비트 연구 데이터">
          <Tabs size="small" items={upbitTabs} />
          <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
            상세 탭(CLEAN·시장·종목·뉴스·LLM·필터 실험)은 위 수집 현황 패널의
            「세부 현황」에서 확인합니다. API는 기존 수집 현황을 재사용합니다.
          </Typography.Paragraph>
        </Card>
      ) : null}

      {showKiwoom ? (
        <Card size="small" title="키움 연구·분석 데이터">
          <Typography.Paragraph type="secondary">
            현재 존재하는 연구/분석 화면으로 연결합니다. 없는 기능은 만들지
            않습니다.
          </Typography.Paragraph>
          <Space orientation="vertical" size={4}>
            <Link href={withMarketQuery(adminRoutes.indicators, "KIWOOM")}>
              기술지표·일봉 이력
            </Link>
            <Link
              href={withMarketQuery(adminRoutes.aiCandidateLifecycle, "KIWOOM")}
            >
              후보 Lifecycle
            </Link>
            <Link
              href={withMarketQuery(adminRoutes.aiMarketAnalyses, "KIWOOM")}
            >
              AI 시장·차트 분석
            </Link>
            <Link href={withMarketQuery(adminRoutes.news, "KIWOOM")}>
              뉴스
            </Link>
            <Link href={withMarketQuery(adminRoutes.disclosures, "KIWOOM")}>
              DART 공시
            </Link>
            <Link href={withMarketQuery(adminRoutes.backtests, "KIWOOM")}>
              백테스트·검증
            </Link>
          </Space>
          <Collapse
            size="small"
            style={{ marginTop: 12 }}
            items={[
              {
                key: "dev",
                label: "개발자 정보",
                children: (
                  <Typography.Text type="secondary">
                    CLEAN Forward / Entry Early-Dump / E1~E8는 업비트 Shadow
                    연구 전용입니다. 키움 KPI와 합산하지 마세요.
                  </Typography.Text>
                ),
              },
            ]}
          />
        </Card>
      ) : null}

      {!showKiwoom && !showUpbit ? (
        <Alert type="info" showIcon title="표시할 시장이 없습니다" />
      ) : null}
    </Space>
  );
}

export default function AdminResearchDataPage() {
  return (
    <AdminPageShell
      title="연구 데이터"
      description="후보·시장·뉴스·AI 연구 수집 현황 (운영 LIVE 제어와 분리)"
    >
      <Suspense fallback={<Typography.Text>시장 선택 로딩…</Typography.Text>}>
        <ResearchWorkspaceBody />
      </Suspense>
    </AdminPageShell>
  );
}
