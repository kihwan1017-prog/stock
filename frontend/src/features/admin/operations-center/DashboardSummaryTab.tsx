"use client";

import { Alert, Card, Col, Row, Segmented, Space, Statistic, Table, Tag, Typography } from "antd";

import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";

import {
  formatKrw,
  formatPct,
  parsePerformanceSummary,
  pnlColor,
  type BrokerFilter,
} from "./autoTradingPerformanceHelpers";
import {
  ChartEmpty,
  SummaryCumulativeChart,
  SummaryDailyChart,
} from "./dashboardCharts";
import { SUMMARY_PERIOD_OPTIONS, type SummaryPeriodFilter } from "./dashboardTabState";
import { useAutotradingPerformanceQuery } from "./useAutotradingPerformanceQuery";
import { useDashboardBrokerOps } from "./useDashboardBrokerOps";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function brokerStatusLabel(card: {
  blocker: string | null;
  readiness?: string | null;
  liveOn: boolean | null;
}): string {
  if (card.blocker) return "차단";
  if (card.liveOn === false) return "중지";
  const r = String(card.readiness ?? "").toUpperCase();
  if (r.includes("READY") || r.includes("RUNNING")) return "자동매매 가능";
  return "준비안됨";
}

type Props = {
  enabled: boolean;
  broker: BrokerFilter;
  summaryPeriod: SummaryPeriodFilter;
  onSummaryPeriodChange: (v: SummaryPeriodFilter) => void;
  refreshMs?: number;
  killActive?: boolean;
};

export function DashboardSummaryTab({
  enabled,
  broker,
  summaryPeriod,
  onSummaryPeriodChange,
  refreshMs = 20_000,
  killActive = false,
}: Props) {
  const brokerOps = useDashboardBrokerOps({
    enabled,
    detailed: false,
    refreshMs,
  });

  const perfQ = useAutotradingPerformanceQuery({
    broker,
    period: summaryPeriod,
    enabled,
    refreshMs,
  });

  const data = rec(perfQ.data);
  const summary = parsePerformanceSummary(data.summary);
  const recent = extractRows(data.recent_closed_trades).slice(0, 5);
  const lowSample = data.low_sample_warning === true;
  const hasTrades = summary.closedTradeCount > 0;

  const showUpbit = broker === "ALL" || broker === "UPBIT";
  const showKiwoom = broker === "ALL" || broker === "KIWOOM";

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card size="small" title="종합 상태">
        <Space wrap>
          {killActive ? (
            <Tag color="error">운영 중지 (Kill Switch)</Tag>
          ) : null}
          {showUpbit ? (
            <Tag
              color={
                brokerOps.upbitCard.blocker ? "warning" : "success"
              }
            >
              UPBIT · {brokerStatusLabel(brokerOps.upbitCard)}
            </Tag>
          ) : null}
          {showKiwoom ? (
            <Tag
              color={
                brokerOps.kiwoomCard.blocker ? "warning" : "default"
              }
            >
              KIWOOM · {brokerStatusLabel(brokerOps.kiwoomCard)}
            </Tag>
          ) : null}
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
              title="AUTO 누적 실현손익"
              value={summary.cumulativeRealizedPnl ?? 0}
              precision={0}
              suffix="원"
              styles={{
                content: { color: pnlColor(summary.cumulativeRealizedPnl) },
              }}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="AUTO 수익률"
              value={formatPct(summary.periodReturnPct)}
            />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="AUTO 거래 횟수" value={summary.closedTradeCount} />
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
            <Statistic title="AUTO 보유종목" value={summary.openPositionCount} />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic
              title="오늘 AUTO 손익"
              value={summary.todayRealizedPnl ?? 0}
              precision={0}
              suffix="원"
              styles={{ content: { color: pnlColor(summary.todayRealizedPnl) } }}
            />
          </Col>
        </Row>
      </Card>

      <Card
        size="small"
        title="핵심 차트"
        extra={
          <Segmented
            size="small"
            value={summaryPeriod}
            onChange={(v) => onSummaryPeriodChange(v as SummaryPeriodFilter)}
            options={SUMMARY_PERIOD_OPTIONS}
          />
        }
        loading={perfQ.isLoading && !perfQ.data}
      >
        {perfQ.isError ? (
          <Alert type="error" title="성과 데이터를 불러오지 못했습니다." />
        ) : !hasTrades ? (
          <ChartEmpty />
        ) : (
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={12}>
              <Typography.Text type="secondary">AUTO 누적손익</Typography.Text>
              <SummaryCumulativeChart data={data} broker={broker} />
            </Col>
            <Col xs={24} lg={12}>
              <Typography.Text type="secondary">AUTO 일별손익</Typography.Text>
              <SummaryDailyChart data={data} />
            </Col>
          </Row>
        )}
      </Card>

      {lowSample && data.low_sample_message ? (
        <Alert type="info" showIcon title={String(data.low_sample_message)} />
      ) : null}

      <Card size="small" title="최근 AUTO 거래 (5건)">
        {recent.length ? (
          <Table
            size="small"
            pagination={false}
            scroll={{ x: 800 }}
            rowKey={(r) => String(rec(r).binding_id ?? rec(r).symbol)}
            dataSource={recent.map((r) => rec(r))}
            columns={[
              { title: "거래소", dataIndex: "broker_code", width: 72 },
              { title: "종목", dataIndex: "symbol" },
              { title: "진입", dataIndex: "entry_price", width: 72 },
              { title: "청산", dataIndex: "exit_price", width: 72 },
              {
                title: "실현손익",
                dataIndex: "net_pnl",
                width: 96,
                render: (v) => formatKrw(Number(v), 2),
              },
              {
                title: "수익률",
                dataIndex: "return_pct",
                width: 72,
                render: (v) => formatPct(Number(v)),
              },
              {
                title: "Exit",
                dataIndex: "exit_reason_label_ko",
                ellipsis: true,
              },
              {
                title: "체결시각",
                dataIndex: "closed_at",
                width: 150,
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
