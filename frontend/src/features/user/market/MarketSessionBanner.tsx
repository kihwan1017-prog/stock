"use client";

import { Alert, Skeleton, Space, Tag } from "antd";

import { toApiError } from "@/lib/api/apiError";

import { sessionPhaseAlertType } from "./sessionPhaseMessages";
import { useMarketSessionStatus } from "./useMarketSessionStatus";

interface MarketSessionBannerProps {
  exchangeCode?: string;
}

/**
 * STEP 8-5-13 — KRX Session Phase 배너. Dashboard/전략/주문 화면에서
 * 공용으로 재사용한다 (Hook 하나 · 시간 계산 중복 없음).
 */
export function MarketSessionBanner({
  exchangeCode = "KRX",
}: MarketSessionBannerProps) {
  const { query, status, phaseMessage } = useMarketSessionStatus(exchangeCode);

  if (query.isLoading) {
    return <Skeleton.Input active size="small" style={{ width: 320 }} />;
  }

  if (query.isError) {
    return (
      <Alert
        type="warning"
        showIcon
        title={`${exchangeCode} 장 상태를 확인할 수 없습니다`}
        description={toApiError(query.error).message}
      />
    );
  }

  if (!status) return null;

  const alertType =
    status.calendar_available === false
      ? "error"
      : sessionPhaseAlertType(status.phase);

  return (
    <Alert
      type={alertType}
      showIcon
      title={
        <Space wrap size={6}>
          <span>{phaseMessage.label}</span>
          {status.is_special_session ? <Tag color="purple">특별 세션</Tag> : null}
          {status.is_delayed_open ? <Tag color="gold">지연개장</Tag> : null}
          {status.is_early_close ? <Tag color="gold">조기종료</Tag> : null}
          {status.snapshot_ready ? (
            <Tag color="cyan">오늘 자산 스냅샷 완료</Tag>
          ) : null}
          {status.analysis_ready ? (
            <Tag color="geekblue">오늘 AI 분석 완료</Tag>
          ) : null}
        </Space>
      }
      description={
        <Space orientation="vertical" size={0}>
          <span>{phaseMessage.description}</span>
          {!status.is_trading_day && status.next_trading_day ? (
            <span>다음 거래일: {status.next_trading_day}</span>
          ) : null}
        </Space>
      }
    />
  );
}
