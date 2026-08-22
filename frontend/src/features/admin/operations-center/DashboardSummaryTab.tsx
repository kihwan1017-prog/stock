"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Col, Row, Space, Statistic, Table, Tag, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { queryKeys } from "@/lib/query/queryKeys";

import {
  formatKrw,
  formatPct,
  parsePerformanceSummary,
  pnlColor,
} from "./autoTradingPerformanceHelpers";
import { useDashboardBrokerOps } from "./useDashboardBrokerOps";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

type Props = {
  enabled: boolean;
  refreshMs?: number;
  killActive?: boolean;
};

export function DashboardSummaryTab({
  enabled,
  refreshMs = 20_000,
  killActive = false,
}: Props) {
  const brokerOps = useDashboardBrokerOps({
    enabled,
    detailed: false,
    refreshMs,
  });

  const perfQ = useQuery({
    queryKey: queryKeys.admin.autotradingPerformance({
      broker: "ALL",
      period: "30D",
    }),
    queryFn: () =>
      adminApi.getAdminAutotradingPerformance({
        broker: "ALL",
        period: "30D",
      }),
    enabled,
    refetchInterval: enabled && refreshMs > 0 ? refreshMs : false,
    staleTime: 45_000,
    placeholderData: (prev) => prev,
  });

  const summary = parsePerformanceSummary(rec(perfQ.data).summary);
  const recent = extractRows(rec(perfQ.data).recent_closed_trades).slice(0, 5);
  const lowSample = rec(perfQ.data).low_sample_warning === true;

  const statusLabel =
    killActive
      ? "운영 중지"
      : brokerOps.overallStatus === "ok"
        ? "전체 정상"
        : brokerOps.overallStatus === "partial"
          ? "일부 차단"
          : "운영 중지";

  const statusColor =
    statusLabel === "전체 정상"
      ? "success"
      : statusLabel === "일부 차단"
        ? "warning"
        : "error";

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="자동매매 종합 상태">
        <Space wrap>
          <Tag color={statusColor}>{statusLabel}</Tag>
          <Tag color={brokerOps.upbitCard.blocker ? "warning" : "success"}>
            UPBIT: {brokerOps.upbitCard.blocker ? "차단" : "정상"}
          </Tag>
          <Tag color={brokerOps.kiwoomCard.blocker ? "warning" : "success"}>
            KIWOOM: {brokerOps.kiwoomCard.blocker ? "차단" : "정상"}
          </Tag>
        </Space>
        {brokerOps.blockers.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            style={{ marginTop: 12 }}
            title="주요 차단"
            description={brokerOps.blockers.slice(0, 2).join(" · ")}
          />
        ) : (
          <Typography.Text type="secondary" style={{ display: "block", marginTop: 8 }}>
            ✅ 현재 안전 차단 없음
          </Typography.Text>
        )}
      </Card>

      <Card
        size="small"
        title="AUTO 성과 KPI"
        loading={perfQ.isLoading && !perfQ.data}
      >
        <Row gutter={[12, 12]}>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="오늘 AUTO 수익률"
              value={formatPct(summary.todayReturnPct)}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="오늘 AUTO 실현손익"
              value={summary.todayRealizedPnl ?? 0}
              precision={0}
              suffix="원"
              styles={{ content: { color: pnlColor(summary.todayRealizedPnl) } }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="현재 AUTO 평가손익"
              value={summary.currentUnrealizedPnl ?? 0}
              precision={0}
              suffix="원"
              styles={{
                content: { color: pnlColor(summary.currentUnrealizedPnl) },
              }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="승률"
              value={
                summary.winRatePct != null
                  ? `${summary.winRatePct.toFixed(1)}%`
                  : "—"
              }
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="완료 거래" value={summary.closedTradeCount} />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="AUTO 보유" value={summary.openPositionCount} />
          </Col>
        </Row>
      </Card>

      <Card size="small" title="계좌 전체 손익 (Safety)">
        <Typography.Text type="secondary">
          MANUAL 보유 평가손익 — AUTO 성과와 분리. 상세는 계좌·자산 화면.
        </Typography.Text>
        <div style={{ marginTop: 8 }}>
          <Statistic
            title="MANUAL 평가손익 (참고)"
            value="—"
            suffix={
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                운영 탭에서 조회
              </Typography.Text>
            }
          />
        </div>
      </Card>

      {lowSample && rec(perfQ.data).low_sample_message ? (
        <Alert
          type="info"
          showIcon
          title={String(rec(perfQ.data).low_sample_message)}
        />
      ) : null}

      <Card size="small" title="최근 AUTO 거래 (5건)">
        {recent.length ? (
          <Table
            size="small"
            pagination={false}
            scroll={{ x: 720 }}
            rowKey={(r) => String(rec(r).binding_id ?? rec(r).symbol)}
            dataSource={recent.map((r) => rec(r))}
            columns={[
              { title: "거래소", dataIndex: "broker_code", width: 80 },
              { title: "종목", dataIndex: "symbol" },
              { title: "진입가", dataIndex: "entry_price", width: 80 },
              { title: "청산가", dataIndex: "exit_price", width: 80 },
              {
                title: "수익률",
                dataIndex: "return_pct",
                width: 80,
                render: (v) => formatPct(Number(v)),
              },
              {
                title: "실현손익",
                dataIndex: "net_pnl",
                width: 100,
                render: (v) => formatKrw(Number(v), 2),
              },
              {
                title: "청산사유",
                dataIndex: "exit_reason_label_ko",
                ellipsis: true,
              },
              {
                title: "시간",
                dataIndex: "closed_at",
                width: 160,
                render: (v) =>
                  v ? new Date(String(v)).toLocaleString("ko-KR") : "—",
              },
            ]}
          />
        ) : (
          <Typography.Text type="secondary">완료된 AUTO 거래 없음</Typography.Text>
        )}
      </Card>
    </Space>
  );
}
