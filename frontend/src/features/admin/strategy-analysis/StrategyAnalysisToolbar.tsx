"use client";

import { Alert, Card, Space, Typography } from "antd";
import type { ReactNode } from "react";

import { MarketSelector } from "@/features/admin/strategy-analysis/MarketSelector";
import {
  isKiwoomVisible,
  isUpbitVisible,
  type StrategyMarket,
} from "@/features/admin/strategy-analysis/marketScope";

type Props = {
  market: StrategyMarket;
  /** 화면 목적 한 줄 (한글) */
  purposeKo?: string;
  children?: ReactNode;
  /** selector를 이 카드 안에 둘지 — false면 selector만 */
  embedded?: boolean;
};

/**
 * 전략·분석 화면 상단 — 시장 선택 + 안내.
 * 키움/업비트 KPI 합산 금지 고지.
 */
export function StrategyAnalysisToolbar({
  market,
  purposeKo,
  children,
  embedded = true,
}: Props) {
  const body = (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <MarketSelector />
      {purposeKo ? (
        <Typography.Text type="secondary">{purposeKo}</Typography.Text>
      ) : null}
      {market === "ALL" ? (
        <Alert
          type="info"
          showIcon
          title="키움·업비트 결과를 하나의 순위로 합산하지 않습니다"
          description="시장별로 따로 확인하세요. 정상 신규 검증(CLEAN)은 업비트 연구 데이터 전용입니다."
        />
      ) : null}
      {children}
    </Space>
  );

  if (!embedded) return body;
  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      {body}
    </Card>
  );
}

export function MarketSection({
  market,
  forMarket,
  title,
  children,
  emptyHint,
}: {
  market: StrategyMarket;
  forMarket: "KIWOOM" | "UPBIT";
  title: string;
  children: ReactNode;
  emptyHint?: string;
}) {
  const visible =
    forMarket === "KIWOOM"
      ? isKiwoomVisible(market)
      : isUpbitVisible(market);
  if (!visible) return null;
  return (
    <Card size="small" title={title} style={{ marginBottom: 12 }}>
      {children}
      {!children && emptyHint ? (
        <Typography.Text type="secondary">{emptyHint}</Typography.Text>
      ) : null}
    </Card>
  );
}
