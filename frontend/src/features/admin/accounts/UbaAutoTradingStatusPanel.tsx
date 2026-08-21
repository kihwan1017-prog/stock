"use client";

/**
 * UBA 자동매매 종합 상태 — readiness API 조회 결과만 표시.
 * LIVE/ARM/Worker/Runtime/주문 변경 없음.
 */

import {
  Alert,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  buildUbaAutoTradingViewModel,
  headlineAlertType,
  recommendationBadgeColor,
  type PassBlock,
  type UbaAutoTradingViewModel,
} from "./ubaAutoTradingStatus";

function onOff(value: boolean | null | undefined): string {
  if (value === true) return "ON";
  if (value === false) return "OFF";
  return "-";
}

function passTag(result: PassBlock) {
  return (
    <Tag color={result === "PASS" ? "green" : "red"}>{result}</Tag>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <Card size="small" title={title} style={{ marginBottom: 8 }}>
      {children}
    </Card>
  );
}

export function UbaAutoTradingStatusPanel({
  ubaId,
  readiness,
  loading,
  errorMessage,
}: {
  ubaId: number;
  readiness: unknown;
  loading?: boolean;
  errorMessage?: string | null;
}) {
  if (loading) {
    return <Typography.Text>자동매매 상태 로딩 중…</Typography.Text>;
  }
  if (errorMessage) {
    return <Alert type="error" showIcon title={errorMessage} />;
  }
  if (!readiness) {
    return (
      <Alert
        type="info"
        showIcon
        title="자동매매 readiness 없음"
        description="상세를 다시 열어 조회하세요."
      />
    );
  }

  const vm: UbaAutoTradingViewModel = buildUbaAutoTradingViewModel(readiness);

  return (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <Alert
        type={headlineAlertType(vm.headline)}
        showIcon
        title={
          <Space wrap>
            <Typography.Text strong style={{ fontSize: 16 }}>
              AUTO TRADING
            </Typography.Text>
            <Tag
              color={
                vm.headline === "READY" || vm.headline === "RUNNING"
                  ? "green"
                  : vm.headline === "PAUSED"
                    ? "blue"
                    : "orange"
              }
              style={{ fontSize: 14, padding: "2px 10px" }}
            >
              {vm.headline}
            </Tag>
            <Typography.Text type="secondary">UBA {ubaId}</Typography.Text>
          </Space>
        }
        description={
          <Space orientation="vertical" size={4}>
            <Typography.Text type="secondary">
              API status: {vm.statusRaw} · final: {vm.finalLabel}
            </Typography.Text>
            {vm.displayBlockers.length > 0 ? (
              <Space wrap size={4}>
                {vm.displayBlockers.map((item) => (
                  <Tag key={item} color="red">
                    {item}
                  </Tag>
                ))}
              </Space>
            ) : (
              <Typography.Text type="success">blockers 없음</Typography.Text>
            )}
            {vm.warnings.length > 0 ? (
              <Typography.Text type="warning">
                warnings: {vm.warnings.join(", ")}
              </Typography.Text>
            ) : null}
          </Space>
        }
      />

      <Section title="Strategy / Runtime">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="strategy_id">
            {vm.strategy.strategyId}
          </Descriptions.Item>
          <Descriptions.Item label="name">{vm.strategy.name}</Descriptions.Item>
          <Descriptions.Item label="symbol">
            {vm.strategy.symbol}
          </Descriptions.Item>
          <Descriptions.Item label="broker">
            {vm.strategy.broker}
          </Descriptions.Item>
          <Descriptions.Item label="strategy active">
            {vm.strategy.strategyActive == null
              ? "-"
              : vm.strategy.strategyActive
                ? "Y"
                : "N"}
          </Descriptions.Item>
          <Descriptions.Item label="link active">
            {vm.strategy.linkActive == null
              ? "-"
              : vm.strategy.linkActive
                ? "Y"
                : "N"}
          </Descriptions.Item>
          <Descriptions.Item label="deployment">
            {vm.strategy.deploymentId}
          </Descriptions.Item>
          <Descriptions.Item label="Runtime">
            <Tag>{vm.strategy.runtimeStatus}</Tag>
          </Descriptions.Item>
        </Descriptions>
      </Section>

      <Section title="Market Feed">
        <Space wrap style={{ marginBottom: 8 }}>
          <Tag color={vm.marketFeed.healthy ? "green" : "red"}>
            {vm.marketFeed.healthy ? "HEALTHY" : "UNHEALTHY"}
          </Tag>
          <Typography.Text type="secondary">
            {vm.marketFeed.reason}
          </Typography.Text>
        </Space>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="Hub">
            {vm.marketFeed.hubStatus}
          </Descriptions.Item>
          <Descriptions.Item label="UPBIT connected/running">
            {onOff(vm.marketFeed.connected)} / {onOff(vm.marketFeed.running)}
          </Descriptions.Item>
          <Descriptions.Item label="subscribed">
            {vm.marketFeed.symbols.join(", ") || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="latest price">
            {vm.marketFeed.latestPrice}
          </Descriptions.Item>
          <Descriptions.Item label="last_received_at">
            {vm.marketFeed.lastReceivedAt}
          </Descriptions.Item>
          <Descriptions.Item label="age / stale">
            {vm.marketFeed.ageSeconds} /{" "}
            {vm.marketFeed.stale == null
              ? "-"
              : vm.marketFeed.stale
                ? "STALE"
                : "OK"}
          </Descriptions.Item>
        </Descriptions>
      </Section>

      <Section title="AI Analysis">
        <Space wrap style={{ marginBottom: 8 }}>
          <Tag
            color={recommendationBadgeColor(vm.aiAnalysis.recommendation)}
            style={{ fontSize: 14, padding: "2px 10px" }}
          >
            {vm.aiAnalysis.recommendation}
          </Tag>
          <Tag color={vm.aiAnalysis.fresh ? "green" : "red"}>
            {vm.aiAnalysis.fresh == null
              ? "N/A"
              : vm.aiAnalysis.fresh
                ? "FRESH"
                : "STALE"}
          </Tag>
          {vm.aiAnalysis.parseNormalizedFallback ? (
            <Tag color="red">AI 응답 정규화/파싱 경고</Tag>
          ) : null}
          <Typography.Text type="secondary">
            {vm.aiAnalysis.parseNormalizedFallback
              ? "파싱 실패 fallback — 시장 HOLD 아님"
              : vm.aiAnalysis.recommendation === "ALLOW"
                ? "주문 허용"
                : vm.aiAnalysis.recommendation === "HOLD"
                  ? "주문 보류"
                  : vm.aiAnalysis.recommendation === "REDUCE"
                    ? "주문금액 축소"
                    : ""}
          </Typography.Text>
        </Space>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="analysis_id">
            {vm.aiAnalysis.analysisId}
          </Descriptions.Item>
          <Descriptions.Item label="analysis_at">
            {vm.aiAnalysis.analysisAt}
          </Descriptions.Item>
          <Descriptions.Item label="analysis_status">
            {vm.aiAnalysis.analysisStatus}
          </Descriptions.Item>
          <Descriptions.Item label="trend / momentum / volatility">
            {vm.aiAnalysis.trend} / {vm.aiAnalysis.momentum} /{" "}
            {vm.aiAnalysis.volatility}
          </Descriptions.Item>
          <Descriptions.Item label="confidence">
            {vm.aiAnalysis.confidence}
          </Descriptions.Item>
          <Descriptions.Item label="risk_level">
            {vm.aiAnalysis.riskLevel}
          </Descriptions.Item>
          <Descriptions.Item label="provider/model">
            {vm.aiAnalysis.provider} / {vm.aiAnalysis.model}
          </Descriptions.Item>
          <Descriptions.Item label="parse warning">
            {vm.aiAnalysis.parseWarning || "-"}
          </Descriptions.Item>
          <Descriptions.Item label="reasons">
            {vm.aiAnalysis.reasons.join("; ") || "-"}
          </Descriptions.Item>
        </Descriptions>
      </Section>

      <Section title="AI Scheduler">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="enabled / running">
            {onOff(vm.aiScheduler.enabled)} / {onOff(vm.aiScheduler.running)}
          </Descriptions.Item>
          <Descriptions.Item label="interval">
            {vm.aiScheduler.intervalSeconds}s
          </Descriptions.Item>
          <Descriptions.Item label="last_run">
            {vm.aiScheduler.lastRun}
          </Descriptions.Item>
          <Descriptions.Item label="last_success">
            {vm.aiScheduler.lastSuccess}
          </Descriptions.Item>
          <Descriptions.Item label="next_run">
            {vm.aiScheduler.nextRun}
          </Descriptions.Item>
          <Descriptions.Item label="success / failure">
            {vm.aiScheduler.successCount} / {vm.aiScheduler.failureCount}
          </Descriptions.Item>
        </Descriptions>
      </Section>

      <Section title="AI Gate">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="Paper Gate">
            {onOff(vm.aiGate.paperOn)}
          </Descriptions.Item>
          <Descriptions.Item label="LIVE Gate">
            <Tag color={vm.aiGate.liveOn ? "green" : "default"}>
              {onOff(vm.aiGate.liveOn)}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="fail_closed">
            {vm.aiGate.failClosed == null
              ? "-"
              : vm.aiGate.failClosed
                ? "YES"
                : "NO"}
          </Descriptions.Item>
          <Descriptions.Item label="AI Recommendation">
            <Tag color={recommendationBadgeColor(vm.aiGate.recommendation)}>
              {vm.aiGate.recommendation}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Gate 판단(가정)">
            {vm.aiGate.assumedResult}
          </Descriptions.Item>
        </Descriptions>
      </Section>

      <Section title="Daily Risk">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="KST date">
            {vm.dailyRisk.kstDate}
          </Descriptions.Item>
          <Descriptions.Item label="Daily Orders (V1 legacy)">
            {vm.dailyRisk.dailyOrderCount} / {vm.dailyRisk.dailyOrderLimit}
          </Descriptions.Item>
          <Descriptions.Item label="Order Limit V2 SUBMIT">
            {vm.dailyRisk.dailySubmitCount} / {vm.dailyRisk.dailySubmitLimit}
          </Descriptions.Item>
          <Descriptions.Item label="Order Limit V2 FILLED ENTRY">
            {vm.dailyRisk.dailyFilledEntryCount} /{" "}
            {vm.dailyRisk.dailyFilledEntryLimit}
          </Descriptions.Item>
          <Descriptions.Item label="Order Limit policy (today)">
            {vm.dailyRisk.orderLimitPolicyVersion}
          </Descriptions.Item>
          <Descriptions.Item label="Order Limit policy (next KRX)">
            {vm.dailyRisk.orderLimitPolicyVersionNextKrx}
            {vm.dailyRisk.orderLimitV2OptedIn ? " · opted-in" : " · not opted-in"}
          </Descriptions.Item>
          <Descriptions.Item label="Max Order">
            {vm.dailyRisk.maxOrderAmount} KRW
          </Descriptions.Item>
          <Descriptions.Item label="Daily Max Order">
            {vm.dailyRisk.dailyMaxOrderAmount} KRW
          </Descriptions.Item>
          <Descriptions.Item label="risk_counted_order_ids">
            {vm.dailyRisk.riskCountedOrderIds}
          </Descriptions.Item>
        </Descriptions>
        <div style={{ marginTop: 8, fontSize: 12 }}>
          <Link href="/admin/risk">리스크 관리 (V1/V2 한도·저장)</Link>
          {" · "}
          <span>
            Strategy PnL API: GET /api/v1/risk/daily-loss/strategy-owned
          </span>
          {" · "}
          <span>
            Runbook: docs/trading/KIWOOM_UBA1381_20260824_ONE_SHOT_REAL_FILL_RUNBOOK.md
          </span>
        </div>
      </Section>

      <Section title="Activation / LIVE / ARM / Worker">
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="Activation">
            <Tag color={vm.ops.activationLabel === "ACTIVE" ? "green" : "red"}>
              {vm.ops.activationLabel}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="transition_id">
            {vm.ops.transitionId}
          </Descriptions.Item>
          <Descriptions.Item label="Activation expires_at">
            {vm.ops.expiresAt}
          </Descriptions.Item>
          <Descriptions.Item label="Activation remaining">
            {vm.ops.remainingTtl}
          </Descriptions.Item>
          <Descriptions.Item label="LIVE">
            <Tag color={vm.ops.liveOn ? "green" : "default"}>
              {onOff(vm.ops.liveOn)}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="ARM">
            <Tag color={vm.ops.armOn ? "green" : "default"}>
              {onOff(vm.ops.armOn)}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="ARM expires">
            {vm.ops.armExpires}
          </Descriptions.Item>
          <Descriptions.Item label="Worker enabled/running">
            {onOff(vm.ops.workerEnabled)} / {onOff(vm.ops.workerRunning)}
          </Descriptions.Item>
          <Descriptions.Item label="pending LIVE outbox">
            {vm.ops.pendingOutbox}
          </Descriptions.Item>
          <Descriptions.Item label="Strategy Runtime">
            <Tag
              color={
                vm.ops.runtimeLifecycle === "RUNNING"
                  ? "green"
                  : vm.ops.runtimeLifecycle === "ERROR"
                    ? "red"
                    : "default"
              }
            >
              {vm.ops.runtimeLifecycle}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Outbox Worker">
            <Tag
              color={
                vm.ops.workerLifecycle === "RUNNING"
                  ? "green"
                  : vm.ops.workerLifecycle === "ERROR"
                    ? "red"
                    : "default"
              }
            >
              {vm.ops.workerLifecycle}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="Exit Monitor">
            <Tag
              color={
                vm.ops.exitMonitorLifecycle === "RUNNING"
                  ? "green"
                  : vm.ops.exitMonitorLifecycle === "ERROR"
                    ? "red"
                    : "default"
              }
            >
              {vm.ops.exitMonitorLifecycle}
            </Tag>
          </Descriptions.Item>
        </Descriptions>
      </Section>

      <Section title="Readiness Checklist">
        <Row gutter={[8, 8]}>
          {vm.checklist.map((item) => (
            <Col span={12} key={item.label}>
              <Space>
                <Typography.Text>{item.label}</Typography.Text>
                {passTag(item.result)}
              </Space>
            </Col>
          ))}
        </Row>
        <Alert
          style={{ marginTop: 12 }}
          type={vm.finalLabel === "READY_FOR_AUTO_TRADING" ? "success" : "warning"}
          showIcon
          title={vm.finalLabel}
          description={
            vm.displayBlockers.length
              ? `blockers: ${vm.displayBlockers.join(" · ")}`
              : "blockers 없음"
          }
        />
      </Section>
    </Space>
  );
}
