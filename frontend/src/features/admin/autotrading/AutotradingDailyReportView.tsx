"use client";

/**
 * 자동매매 일일 운영보고 — READ ONLY UI (REAL decision 무영향).
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Empty,
  Row,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs, { type Dayjs } from "dayjs";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import {
  OpsFunnelSteps,
  formatOverallHealth,
  formatWhyNoTradeReason,
  type FunnelStep,
} from "@/features/admin/ops-ux";
import { adminRoutes } from "@/config/routes";
import Link from "next/link";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function fmtKrw(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return `${Math.round(n).toLocaleString("ko-KR")}원`;
}

function pipelineToFunnel(pipeline: Record<string, unknown>): FunnelStep[] {
  const order: Array<{ key: string; label: string }> = [
    { key: "CANDIDATE_SELECTED", label: "후보" },
    { key: "TECHNICAL_PASS", label: "기술 통과" },
    { key: "SIGNAL_EMITTED", label: "신호" },
    { key: "EXECUTOR_RECEIVED", label: "실행기" },
    { key: "ORDER_CREATED", label: "주문" },
    { key: "BUY_FILLED", label: "체결" },
  ];
  const altKeys: Record<string, string[]> = {
    CANDIDATE_SELECTED: ["candidate", "candidates", "CANDIDATE"],
    TECHNICAL_PASS: ["technical_pass", "ENTRY_PASS"],
    SIGNAL_EMITTED: ["signal_emitted", "signals"],
    EXECUTOR_RECEIVED: ["executor_received", "executor"],
    ORDER_CREATED: ["order_created", "orders", "ORDER_PERSISTED"],
    BUY_FILLED: ["buy_filled", "fills", "FILLED"],
  };
  return order
    .map(({ key, label }) => {
      let count = Number(pipeline[key]);
      if (!Number.isFinite(count)) {
        for (const alt of altKeys[key] ?? []) {
          const n = Number(pipeline[alt]);
          if (Number.isFinite(n)) {
            count = n;
            break;
          }
        }
      }
      if (!Number.isFinite(count)) return null;
      return { key, label, count };
    })
    .filter((s): s is FunnelStep => s != null);
}

type MarketSectionProps = {
  title: string;
  data: Record<string, unknown> | null;
};

function MarketDailyCard({ title, data }: MarketSectionProps) {
  if (!data) return null;
  const ts = rec(data.trading_summary);
  const whyRaw = Array.isArray(data.why_no_trade)
    ? (data.why_no_trade as string[])
    : [];
  const why = whyRaw.map((w) => formatWhyNoTradeReason(w));
  const positions = extractRows(data.open_positions);
  const pipeline = rec(data.pipeline);
  const dailyEntry = rec(data.daily_entry);
  const funnel = pipelineToFunnel(pipeline);

  const posColumns: ColumnsType<Record<string, unknown>> = [
    { title: "종목", dataIndex: "symbol", key: "symbol" },
    { title: "수량", dataIndex: "quantity", key: "quantity" },
    {
      title: "미실현",
      dataIndex: "unrealized_pnl",
      key: "unrealized_pnl",
      render: (v) => fmtKrw(v),
    },
  ];

  return (
    <Card title={title} style={{ marginBottom: 16 }}>
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Tag color="blue">{String(data.health_label ?? "—")}</Tag>
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
          <Descriptions.Item label="자동매매">
            {String(data.auto_trading_state ?? "—")}
          </Descriptions.Item>
          <Descriptions.Item label="시세">
            {String(data.feed_status ?? "—")}
          </Descriptions.Item>
          <Descriptions.Item label="데이터 신뢰">
            {String(rec(data.data_trust).quality_status ?? "—")}
          </Descriptions.Item>
          <Descriptions.Item label="LIVE">
            {String(data.live ?? "—")}
          </Descriptions.Item>
          <Descriptions.Item label="ARM">
            {String(data.arm ?? "—")}
          </Descriptions.Item>
          {"market_session" in data ? (
            <Descriptions.Item label="시장">
              {String(data.market_session ?? "—")}
            </Descriptions.Item>
          ) : null}
        </Descriptions>

        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <Statistic title="매수" value={Number(ts.buy_order_count ?? 0)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="매도" value={Number(ts.sell_order_count ?? 0)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="체결"
              value={Number(ts.buy_fill_count ?? 0) + Number(ts.sell_fill_count ?? 0)}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="보유"
              value={Number(ts.open_position_count ?? 0)}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="실현손익" value={fmtKrw(ts.realized_pnl)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="미실현손익" value={fmtKrw(ts.unrealized_pnl)} />
          </Col>
        </Row>

        {dailyEntry && Object.keys(dailyEntry).length > 0 ? (
          <Alert
            type="info"
            showIcon
            title="오늘 신규 진입"
            description={`${dailyEntry.consumed ?? dailyEntry.entry_count ?? "—"} / ${dailyEntry.limit ?? dailyEntry.daily_limit ?? "—"} (잔여 ${dailyEntry.remaining ?? "—"})`}
          />
        ) : null}

        {why.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            title="왜 거래하지 않았나요?"
            description={why.join(" · ")}
          />
        ) : null}

        {funnel.length > 0 ? (
          <OpsFunnelSteps title={`${title} 거래 흐름 (오늘 누적)`} steps={funnel} />
        ) : Object.keys(pipeline).length > 0 ? (
          <Card size="small" title="파이프라인 (고급)">
            <Descriptions size="small" column={2}>
              {Object.entries(pipeline).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>
                  {String(v)}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </Card>
        ) : null}

        <Table
          size="small"
          rowKey={(r) => String(r.symbol ?? r.binding_id ?? Math.random())}
          columns={posColumns}
          dataSource={positions}
          pagination={false}
          locale={{ emptyText: "현재 보유 중인 종목이 없습니다." }}
        />
      </Space>
    </Card>
  );
}

export function AutotradingDailyReportView() {
  const [reportDay, setReportDay] = useState<Dayjs>(() => dayjs());

  const dateStr = reportDay.format("YYYY-MM-DD");
  const reportQ = useQuery({
    queryKey: ["admin", "autotrading-daily-report", dateStr],
    queryFn: () => adminApi.getAutotradingDailyReport({ date: dateStr, market: "ALL" }),
    staleTime: 60_000,
  });

  const data = rec(reportQ.data);
  const incidents = rec(data.incidents);
  const incidentItems = extractRows(incidents.items);
  const research = rec(data.research);
  const upbitResearch = rec(research.upbit ?? research.UPBIT);
  const kiwoomResearch = rec(research.kiwoom ?? research.KIWOOM);
  const upbitSamples = rec(upbitResearch.samples);
  const kiwoomSamples = rec(kiwoomResearch.samples);
  const upbitE0 = rec(upbitSamples.E0);
  const upbitE2 = rec(upbitSamples.E2);
  const kiwoomK0 = rec(kiwoomSamples.K0);

  const researchNote = useMemo(
    () =>
      "연구 데이터이며 실제 주문에는 영향을 주지 않습니다.",
    [],
  );

  return (
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <Space wrap>
        <DatePicker
          value={reportDay}
          onChange={(v) => v && setReportDay(v)}
          allowClear={false}
        />
        <Typography.Text type="secondary">
          KST 기준 · 조회 전용 (REAL/LIVE/주문 변경 없음)
        </Typography.Text>
      </Space>

      {reportQ.isLoading ? <Spin /> : null}
      {reportQ.isError ? (
        <Alert type="error" showIcon title="일일 운영보고를 불러오지 못했습니다." />
      ) : null}

      {!reportQ.isLoading && !reportQ.isError ? (
        <>
          <Alert
            type={
              String(data.overall_health_code ?? "").toUpperCase() === "RED"
                ? "error"
                : String(data.overall_health_code ?? "").toUpperCase() === "ORANGE"
                  ? "warning"
                  : "success"
            }
            showIcon
            title={`오늘 운영 상태: ${formatOverallHealth(data.overall_health_code).label}`}
            description={`보고일 ${String(data.report_date_kst ?? dateStr)} · ${String(data.overall_health_label ?? "")} · 조회 전용`}
          />

          <Space wrap>
            <Link href={adminRoutes.autotradingUpbit}>업비트 자세히 →</Link>
            <Link href={adminRoutes.autotradingKiwoom}>키움 자세히 →</Link>
            <Link href={adminRoutes.orders}>주문·체결 →</Link>
          </Space>

          <MarketDailyCard title="업비트" data={rec(data.upbit)} />
          <MarketDailyCard title="키움" data={rec(data.kiwoom)} />

          <Card title="시스템 장애 (당일)" size="small">
            {incidentItems.length === 0 ? (
              <Empty description="당일 기록된 장애가 없습니다." />
            ) : (
              <Table
                size="small"
                rowKey={(r) => String(r.incident_id ?? r.signature)}
                dataSource={incidentItems}
                pagination={false}
                columns={[
                  { title: "시장", dataIndex: "market", width: 80 },
                  { title: "내용", dataIndex: "signature" },
                  {
                    title: "시작",
                    dataIndex: "started_at",
                    render: (v) => String(v ?? "").slice(0, 16),
                  },
                  {
                    title: "복구",
                    dataIndex: "recovered",
                    render: (v) => (v ? "완료" : "미복구"),
                  },
                ]}
              />
            )}
          </Card>

          <Card title="연구·Shadow (실주문 아님)" size="small">
            <Typography.Paragraph type="secondary">{researchNote}</Typography.Paragraph>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Typography.Text strong>업비트</Typography.Text>
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="자연 기회 풀">
                    {String(upbitResearch.NATURAL_OPPORTUNITY_POOL ?? "—")}
                  </Descriptions.Item>
                  <Descriptions.Item label="E0 유효 표본">
                    {String(upbitE0.VALID_SAMPLE ?? "—")}
                  </Descriptions.Item>
                  <Descriptions.Item label="E2 유효 표본">
                    {String(upbitE2.VALID_SAMPLE ?? "—")}
                  </Descriptions.Item>
                </Descriptions>
              </Col>
              <Col xs={24} md={12}>
                <Typography.Text strong>키움</Typography.Text>
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="K0 표본">
                    {String(kiwoomK0.VALID_SAMPLE ?? "—")}
                  </Descriptions.Item>
                </Descriptions>
              </Col>
            </Row>
          </Card>
        </>
      ) : null}
    </Space>
  );
}
