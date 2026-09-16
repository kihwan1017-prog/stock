"use client";

/**
 * AUTO trading performance — strategy-owned PnL only (MANUAL/계좌전체 분리).
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Empty,
  Radio,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { queryKeys } from "@/lib/query/queryKeys";

import {
  BROKER_FILTER_OPTIONS,
  durationLabel,
  formatKrw,
  formatPct,
  parsePerformanceSummary,
  PERIOD_FILTER_OPTIONS,
  pnlColor,
  type BrokerFilter,
  type PeriodFilter,
} from "./autoTradingPerformanceHelpers";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

type Props = {
  refreshMs?: number;
};

export function AutoTradingPerformancePanel({ refreshMs = 60_000 }: Props) {
  const [broker, setBroker] = useState<BrokerFilter>("ALL");
  const [period, setPeriod] = useState<PeriodFilter>("30D");

  const perfQ = useQuery({
    queryKey: queryKeys.admin.autotradingPerformance({ broker, period }),
    queryFn: () =>
      adminApi.getAdminAutotradingPerformance({ broker, period }),
    refetchInterval: refreshMs > 0 ? refreshMs : false,
    staleTime: 45_000,
    placeholderData: (prev) => prev,
  });

  const data = rec(perfQ.data);
  const summary = parsePerformanceSummary(data.summary);
  const symbolRows = extractRows(data.symbol_performance);
  const exitRows = extractRows(data.exit_reason_performance);
  const recentRows = extractRows(data.recent_closed_trades);
  const openRows = extractRows(data.open_positions);
  const winLoss = rec(data.win_loss);
  const distRows = extractRows(data.return_distribution);
  const brokerCmp = extractRows(data.broker_comparison);

  const dailyChart = useMemo(() => {
    const rows = extractRows(rec(perfQ.data).daily_returns);
    return rows.map((r) => {
      const row = rec(r);
      return {
        date: String(row.trading_date ?? "").slice(5),
        daily_return_pct: Number(row.daily_return_pct ?? 0),
        realized_pnl: Number(row.realized_pnl ?? 0),
        trade_count: Number(row.trade_count ?? 0),
      };
    });
  }, [perfQ.data]);

  const cumulativeChart = useMemo(() => {
    const rows = extractRows(rec(perfQ.data).cumulative_returns);
    return rows.map((r) => {
      const row = rec(r);
      return {
        date: String(row.trading_date ?? "").slice(5),
        cumulative_return_pct: Number(row.cumulative_return_pct ?? 0),
        cumulative_realized_pnl: Number(row.cumulative_realized_pnl ?? 0),
      };
    });
  }, [perfQ.data]);

  const hasClosed = summary.closedTradeCount > 0;
  const lowSample = data.low_sample_warning === true;
  const feeIncomplete =
    data.fee_incomplete === true ||
    rec(data.summary).fee_incomplete === true ||
    Boolean(data.fee_incomplete_display_note_ko);

  const filters = (
    <Space wrap>
      <Radio.Group
        size="small"
        optionType="button"
        value={broker}
        onChange={(e) => setBroker(e.target.value)}
        options={BROKER_FILTER_OPTIONS}
      />
      <Radio.Group
        size="small"
        optionType="button"
        value={period}
        onChange={(e) => setPeriod(e.target.value)}
        options={PERIOD_FILTER_OPTIONS}
      />
    </Space>
  );

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="자동매매 성과 (AUTO 전용)"
        description={
          String(
            data.exclusion_rule ??
              "AUTO ownership 확인 거래만 집계. 일반매매·Shadow 제외.",
          )
        }
      />

      {lowSample && data.low_sample_message ? (
        <Alert type="warning" showIcon title={String(data.low_sample_message)} />
      ) : null}

      {feeIncomplete ? (
        <Alert
          type="warning"
          showIcon
          title="수수료 기록 불완전"
          description={
            String(
              data.fee_incomplete_display_note_ko ??
                "일부 체결에 upbit_paid_fee/binding.fees가 비어 NET PnL이 왜곡될 수 있습니다.",
            )
          }
        />
      ) : null}

      <Card
        size="small"
        title="자동매매 성과 KPI"
        extra={filters}
        loading={perfQ.isLoading && !perfQ.data}
      >
        <Row gutter={[12, 12]}>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="오늘 AUTO 실현손익"
              value={summary.todayRealizedPnl ?? 0}
              precision={0}
              suffix="원"
              styles={{
                content: { color: pnlColor(summary.todayRealizedPnl) },
              }}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="오늘 AUTO 수익률"
              value={formatPct(summary.todayReturnPct)}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="누적 AUTO 실현손익"
              value={summary.cumulativeRealizedPnl ?? 0}
              precision={0}
              suffix="원"
              styles={{
                content: { color: pnlColor(summary.cumulativeRealizedPnl) },
              }}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="누적 AUTO 수익률"
              value={formatPct(summary.cumulativeReturnPct)}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
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
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="승률"
              value={
                summary.winRatePct != null
                  ? `${summary.winRatePct.toFixed(1)}%`
                  : "—"
              }
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="완료 거래"
              value={summary.closedTradeCount}
            />
          </Col>
          <Col xs={12} sm={8} md={6} lg={4}>
            <Statistic
              title="AUTO 보유"
              value={summary.openPositionCount}
            />
          </Col>
        </Row>
        <Typography.Paragraph
          type="secondary"
          style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}
        >
          {String(data.return_formula_note ?? "")}
        </Typography.Paragraph>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card size="small" title="일별 자동매매 수익률" loading={perfQ.isLoading}>
            {!hasClosed ? (
              <Empty description="거래 데이터 없음" />
            ) : (
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={dailyChart}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis unit="%" />
                    <Tooltip
                      formatter={(v: number, name: string) =>
                        name.includes("수익률") ? `${v}%` : formatKrw(v)
                      }
                    />
                    <Bar dataKey="daily_return_pct" name="수익률(%)">
                      {dailyChart.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={
                            entry.daily_return_pct >= 0 ? "#3f8600" : "#cf1322"
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="누적 자동매매 수익률" loading={perfQ.isLoading}>
            {!hasClosed ? (
              <Empty description="거래 데이터 없음" />
            ) : (
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <LineChart data={cumulativeChart}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" />
                    <YAxis unit="%" />
                    <Tooltip />
                    <Line
                      type="monotone"
                      dataKey="cumulative_return_pct"
                      name="누적 수익률(%)"
                      stroke="#1677ff"
                      dot
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card size="small" title="종목별 자동매매 성과">
            {symbolRows.length ? (
              <Table
                size="small"
                pagination={false}
                rowKey="symbol"
                dataSource={symbolRows.map((r) => rec(r))}
                columns={[
                  { title: "종목", dataIndex: "symbol", key: "symbol" },
                  {
                    title: "실현손익",
                    dataIndex: "realized_pnl",
                    key: "pnl",
                    render: (v) => formatKrw(Number(v)),
                  },
                  {
                    title: "수익률",
                    dataIndex: "return_pct",
                    key: "ret",
                    render: (v) => formatPct(Number(v)),
                  },
                  { title: "거래", dataIndex: "trade_count", key: "cnt" },
                ]}
              />
            ) : (
              <Empty description="거래 데이터 없음" />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card size="small" title="청산 유형별 성과">
            {exitRows.length ? (
              <Table
                size="small"
                pagination={false}
                rowKey="exit_reason_category"
                dataSource={exitRows.map((r) => rec(r))}
                columns={[
                  {
                    title: "유형",
                    dataIndex: "exit_reason_label_ko",
                    key: "label",
                  },
                  { title: "거래", dataIndex: "trade_count", key: "cnt" },
                  {
                    title: "평균 수익률",
                    dataIndex: "avg_return_pct",
                    key: "avg",
                    render: (v) => formatPct(Number(v)),
                  },
                  {
                    title: "실현손익",
                    dataIndex: "total_realized_pnl",
                    key: "pnl",
                    render: (v) => formatKrw(Number(v)),
                  },
                ]}
              />
            ) : (
              <Empty description="거래 데이터 없음" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <Card size="small" title="승/패 분포">
            <Space>
              <Tag color="success">WIN {Number(winLoss.wins ?? 0)}</Tag>
              <Tag color="error">LOSS {Number(winLoss.losses ?? 0)}</Tag>
              <Tag>FLAT {Number(winLoss.flats ?? 0)}</Tag>
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={16}>
          <Card size="small" title="브로커 비교">
            <Table
              size="small"
              pagination={false}
              rowKey="broker_code"
              dataSource={brokerCmp.map((r) => rec(r))}
              columns={[
                { title: "브로커", dataIndex: "broker_code", key: "b" },
                {
                  title: "상태",
                  key: "st",
                  render: (_, row) =>
                    row.has_trades === false
                      ? String(row.label ?? "거래 없음")
                      : `${row.trade_count}건`,
                },
                {
                  title: "실현손익",
                  dataIndex: "realized_pnl",
                  key: "pnl",
                  render: (v) =>
                    v == null ? "—" : formatKrw(Number(v)),
                },
                {
                  title: "수익률",
                  dataIndex: "return_pct",
                  key: "ret",
                  render: (v) =>
                    v == null ? "—" : formatPct(Number(v)),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {hasClosed && distRows.some((r) => Number(rec(r).count) > 0) ? (
        <Card size="small" title="수익률 구간 분포">
          <div style={{ width: "100%", height: 200 }}>
            <ResponsiveContainer>
              <BarChart
                data={distRows.map((r) => {
                  const row = rec(r);
                  return {
                    bucket: String(row.bucket),
                    count: Number(row.count ?? 0),
                  };
                })}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="bucket" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" name="거래수" fill="#1677ff" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card size="small" title="최근 AUTO 거래">
            {recentRows.length ? (
              <Table
                size="small"
                pagination={false}
                rowKey={(r) =>
                  String(rec(r).binding_id ?? rec(r).symbol)
                }
                scroll={{ x: 800 }}
                dataSource={recentRows.map((r) => rec(r))}
                columns={[
                  {
                    title: "브로커",
                    dataIndex: "broker_code",
                    key: "broker",
                  },
                  { title: "종목", dataIndex: "symbol", key: "sym" },
                  {
                    title: "진입",
                    dataIndex: "entry_price",
                    key: "entry",
                  },
                  {
                    title: "청산",
                    dataIndex: "exit_price",
                    key: "exit",
                  },
                  {
                    title: "순손익",
                    dataIndex: "net_pnl",
                    key: "pnl",
                    render: (v) => formatKrw(Number(v), 2),
                  },
                  {
                    title: "수익률",
                    dataIndex: "return_pct",
                    key: "ret",
                    render: (v) => formatPct(Number(v)),
                  },
                  {
                    title: "청산사유",
                    dataIndex: "exit_reason_label_ko",
                    key: "reason",
                  },
                  {
                    title: "보유",
                    key: "dur",
                    render: (_, row) =>
                      durationLabel(
                        Number(row.duration_sec) || null,
                      ),
                  },
                ]}
              />
            ) : (
              <Empty description="완료된 AUTO 거래 없음" />
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card size="small" title="OPEN AUTO 포지션">
            {openRows.length ? (
              <Table
                size="small"
                pagination={false}
                rowKey={(r) => String(rec(r).binding_id)}
                dataSource={openRows.map((r) => rec(r))}
                columns={[
                  { title: "종목", dataIndex: "symbol", key: "sym" },
                  {
                    title: "평가손익",
                    dataIndex: "unrealized_pnl",
                    key: "pnl",
                    render: (v) => formatKrw(Number(v), 2),
                  },
                  {
                    title: "수익률",
                    dataIndex: "unrealized_return_pct",
                    key: "ret",
                    render: (v) => formatPct(Number(v)),
                  },
                ]}
              />
            ) : (
              <Empty description="OPEN AUTO 포지션 없음" />
            )}
          </Card>
        </Col>
      </Row>
    </Space>
  );
}
