"use client";

/**
 * 전략·분석 → 연구 데이터 워크스페이스.
 * UPBIT: 수집 현황 + CLEAN/시장/종목/뉴스/LLM/필터 실험 상세.
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
import { UpbitMaExitForwardShadowPanel } from "@/features/admin/upbit/UpbitMaExitForwardShadowPanel";
import { UpbitEntrySignalShadowPanel } from "@/features/admin/upbit/UpbitEntrySignalShadowPanel";
import { CrossMarketShadowResearchPanel } from "@/features/admin/research/CrossMarketShadowResearchPanel";
import { upbitResearchDetailTabs } from "@/features/admin/upbit/UpbitResearchDetailWorkspace";
import { KiwoomRagFeedbackTab } from "@/features/admin/upbit/KiwoomResearchRagFeedback";
import { DEFAULT_UPBIT_AUTOTRADING_UBA_ID } from "@/features/admin/upbit/upbitAutotradingSettingsConfig";

function ResearchWorkspaceBody() {
  const market = useStrategyMarketFromUrl();
  const [ubaId] = useState(DEFAULT_UPBIT_AUTOTRADING_UBA_ID);
  const showKiwoom = isKiwoomVisible(market);
  const showUpbit = isUpbitVisible(market);

  const {
    CleanForwardTab,
    MarketTab,
    AssetTab,
    NewsTab,
    LlmTab,
    ExperimentsTab,
    RagFeedbackTab,
  } = upbitResearchDetailTabs;

  const upbitTabs = useMemo(
    () => [
      {
        key: "status",
        label: "수집 현황",
        children: <UpbitResearchCollectionStatusPanel ubaId={ubaId} />,
      },
      {
        key: "clean",
        label: (
          <span>
            정상 신규 검증 표본{" "}
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              CLEAN
            </Typography.Text>
          </span>
        ),
        children: <CleanForwardTab />,
      },
      {
        key: "market",
        label: "시장 데이터",
        children: <MarketTab />,
      },
      {
        key: "asset",
        label: "종목 데이터",
        children: <AssetTab />,
      },
      {
        key: "news",
        label: "뉴스·공지",
        children: <NewsTab />,
      },
      {
        key: "llm",
        label: "AI 분석 결과",
        children: <LlmTab />,
      },
      {
        key: "rag",
        label: "RAG / Feedback",
        children: <RagFeedbackTab />,
      },
      {
        key: "exit-forward-shadow",
        label: "Exit Forward Shadow",
        children: <UpbitMaExitForwardShadowPanel ubaId={ubaId} />,
      },
      {
        key: "entry-signal-shadow",
        label: "Entry Signal Shadow",
        children: <UpbitEntrySignalShadowPanel ubaId={ubaId} />,
      },
      {
        key: "experiments",
        label: "필터 실험",
        children: <ExperimentsTab />,
      },
    ],
    [
      ubaId,
      CleanForwardTab,
      MarketTab,
      AssetTab,
      NewsTab,
      LlmTab,
      ExperimentsTab,
      RagFeedbackTab,
    ],
  );

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="연구 데이터 — 실제 주문에 사용되지 않음"
        description="Shadow/실험 결과입니다. LIVE·ARM·실주문 경로와 분리되어 있습니다."
      />
      <StrategyAnalysisToolbar
        market={market}
        purposeKo="연구·검증용 데이터만 모읍니다. 실주문·LIVE/ARM과는 분리됩니다."
      />

      {(showUpbit || showKiwoom || market === "ALL") ? (
        <CrossMarketShadowResearchPanel
          upbitUbaId={ubaId}
          kiwoomUbaId={1381}
        />
      ) : null}

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
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            Scanner 후보 → 기술지표 → 시장/종목 Context → 뉴스 → LLM → CLEAN
            Forward → 필터 실험을 개별 row로 추적합니다. READ-ONLY.
          </Typography.Paragraph>
          <Tabs size="small" items={upbitTabs} />
        </Card>
      ) : null}

      {showKiwoom ? (
        <Card size="small" title="키움 연구·분석 데이터">
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            KIWOOM Dual LLM SHADOW · RAG/Feedback는 UPBIT와 격리됩니다. 없는
            데이터는 EMPTY로 표시하며 placeholder row를 만들지 않습니다.
          </Typography.Paragraph>
          <Tabs
            size="small"
            items={[
              {
                key: "rag",
                label: "RAG / Feedback",
                children: <KiwoomRagFeedbackTab />,
              },
              {
                key: "links",
                label: "기존 연구 링크",
                children: (
                  <Space orientation="vertical" size={4}>
                    <Link
                      href={withMarketQuery(adminRoutes.indicators, "KIWOOM")}
                    >
                      기술지표·일봉 이력
                    </Link>
                    <Link
                      href={withMarketQuery(
                        adminRoutes.aiCandidateLifecycle,
                        "KIWOOM",
                      )}
                    >
                      후보 Lifecycle
                    </Link>
                    <Link
                      href={withMarketQuery(
                        adminRoutes.aiMarketAnalyses,
                        "KIWOOM",
                      )}
                    >
                      AI 시장·차트 분석
                    </Link>
                    <Link href={withMarketQuery(adminRoutes.news, "KIWOOM")}>
                      뉴스
                    </Link>
                    <Link
                      href={withMarketQuery(adminRoutes.disclosures, "KIWOOM")}
                    >
                      DART 공시
                    </Link>
                  </Space>
                ),
              },
            ]}
          />
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
                    연구 전용입니다. 키움 KPI와 합산하지 마세요. KIWOOM Dual LLM
                    SHADOW도 UPBIT RAG와 혼합하지 않습니다.
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
      description="후보·시장·뉴스·AI 연구 수집 및 상세 drill-down (운영 LIVE 제어와 분리)"
    >
      <Suspense fallback={<Typography.Text>시장 선택 로딩…</Typography.Text>}>
        <ResearchWorkspaceBody />
      </Suspense>
    </AdminPageShell>
  );
}
