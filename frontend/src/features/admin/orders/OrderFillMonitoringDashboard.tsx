/**
 * 주문·체결 모니터링 대시보드 — AUTO 중심 READ projection.
 * 수동/Paper mutation UI는 page의 운영 도구 Collapse에 둔다.
 */

"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Empty,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import * as adminApi from "@/features/admin/api/adminApi";
import { resolveOrderTradingKind } from "@/features/admin/autotrading/orderOwnership";
import {
  formatKrw,
  formatPct,
  pnlColor,
  type BrokerFilter,
} from "@/features/admin/operations-center/autoTradingPerformanceHelpers";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import {
  orderStatusLabelKo,
  sideLabelKo,
} from "@/features/shared/display/tradingDisplayLabelsKo";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { adminRoutes } from "@/config/routes";
import { cell } from "@/shared/utils/dataHelpers";

import {
  buildHourlyFillFlow,
  filterOrdersForMonitor,
  filledOrdersForTooltip,
  kstTodayStartIso,
  matchesMarket,
  numOrNull,
  summarizeDayOrders,
  type MarketFilter,
  type OrderRow,
  type OwnershipFilter,
} from "./orderFillMonitoringHelpers";

const UBA_UPBIT = 1380;
const UBA_KIWOOM = 1381;

type Props = {
  onOpenDetail: (orderId: number) => void;
};

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

export function OrderFillMonitoringDashboard({ onOpenDetail }: Props) {
  const [market, setMarket] = useState<MarketFilter>("ALL");
  const [ownership, setOwnership] = useState<OwnershipFilter>("AUTO");
  const [symbol, setSymbol] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string>("ALL");
  const [pnlSort, setPnlSort] = useState<"profit" | "loss">("profit");
  const todayStart = useMemo(() => new Date(kstTodayStartIso()), []);

  const perfBroker: BrokerFilter =
    market === "ALL" ? "ALL" : market === "UPBIT" ? "UPBIT" : "KIWOOM";

  const ordersQ = useQuery({
    queryKey: queryKeys.admin.orders({ limit: 300, offset: 0 }),
    queryFn: () => adminApi.listOrders({ limit: 300, offset: 0 }),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const perfQ = useQuery({
    queryKey: queryKeys.admin.autotradingPerformance({
      broker: perfBroker,
      period: "TODAY",
      includeOps: true,
    }),
    queryFn: () =>
      adminApi.getAdminAutotradingPerformance({
        broker: perfBroker,
        period: "TODAY",
        include_ops: true,
      }),
    refetchInterval: 60_000,
    staleTime: 45_000,
  });

  const pipeUpbitQ = useQuery({
    queryKey: ["admin", "pipeline-liveness", UBA_UPBIT],
    queryFn: () => adminApi.getAdminUbaPipelineLiveness(UBA_UPBIT),
    enabled: market === "ALL" || market === "UPBIT",
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const pipeKiwoomQ = useQuery({
    queryKey: ["admin", "pipeline-liveness", UBA_KIWOOM],
    queryFn: () => adminApi.getAdminUbaPipelineLiveness(UBA_KIWOOM),
    enabled: market === "ALL" || market === "KIWOOM",
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const allRows = useMemo(
    () => extractRows(ordersQ.data) as OrderRow[],
    [ordersQ.data],
  );

  const filtered = useMemo(() => {
    const base = filterOrdersForMonitor(allRows, {
      market,
      ownership,
      symbol,
      todayOnly: true,
      todayStart,
    });
    if (statusFilter === "ALL") return base;
    return base.filter(
      (r) => String(r.status_code ?? "").toUpperCase() === statusFilter,
    );
  }, [allRows, market, ownership, symbol, todayStart, statusFilter]);

  const daySummary = useMemo(() => summarizeDayOrders(filtered), [filtered]);
  const hourly = useMemo(() => buildHourlyFillFlow(filtered), [filtered]);

  const perf = rec(perfQ.data);
  const winLoss = rec(perf.win_loss);
  const summary = rec(perf.summary);
  const realizedPnl = numOrNull(summary.today_realized_pnl ?? summary.period_realized_pnl);
  const wins = Number(winLoss.wins ?? 0);
  const losses = Number(winLoss.losses ?? 0);
  const winRate = numOrNull(winLoss.win_rate_pct ?? summary.win_rate_pct);

  const symbolChart = useMemo(() => {
    const rows = extractRows(perf.symbol_performance).map((r) => {
      const row = rec(r);
      return {
        symbol: String(row.symbol ?? "—"),
        net_pnl: Number(row.realized_pnl ?? 0),
        trade_count: Number(row.trade_count ?? 0),
      };
    });
    rows.sort((a, b) =>
      pnlSort === "profit" ? b.net_pnl - a.net_pnl : a.net_pnl - b.net_pnl,
    );
    return rows;
  }, [perf.symbol_performance, pnlSort]);

  const exitRows = useMemo(() => {
    return extractRows(perf.exit_reason_performance).map((r) => {
      const row = rec(r);
      return {
        key: String(row.exit_reason_category ?? "OTHER"),
        label: String(row.exit_reason_label_ko ?? row.exit_reason_category ?? "—"),
        count: Number(row.trade_count ?? 0),
        wins: Number(row.win_count ?? 0),
        losses: Number(row.loss_count ?? 0),
        net: Number(row.total_realized_pnl ?? 0),
      };
    });
  }, [perf.exit_reason_performance]);

  const closedByOrderId = useMemo(() => {
    const map = new Map<number, Record<string, unknown>>();
    for (const t of extractRows(perf.round_trips).concat(
      extractRows(perf.recent_closed_trades),
    )) {
      const row = rec(t);
      const entryId = Number(row.entry_order_id);
      const exitId = Number(row.exit_order_id);
      if (Number.isFinite(entryId)) map.set(entryId, row);
      if (Number.isFinite(exitId)) map.set(exitId, row);
    }
    return map;
  }, [perf.round_trips, perf.recent_closed_trades]);

  // 오늘 데이터 신뢰 — UPBIT pipeline SoT 우선 (시장 ALL일 때도 대표 표시)
  const dataTrustQs = useMemo(() => {
    const src =
      market === "KIWOOM" ? rec(pipeKiwoomQ.data) : rec(pipeUpbitQ.data);
    const dt = rec(src.data_trust);
    return String(dt.quality_status || "").toUpperCase();
  }, [market, pipeKiwoomQ.data, pipeUpbitQ.data]);
  const dataTrustLabel =
    dataTrustQs === "VALID"
      ? "오늘 데이터 신뢰: 정상"
      : dataTrustQs === "DEGRADED"
        ? "오늘 데이터 신뢰: 주의"
        : dataTrustQs === "INVALID"
          ? "오늘 데이터 신뢰: 분석 제외"
          : dataTrustQs === "UNKNOWN"
            ? "오늘 데이터 신뢰: 미확정"
            : null;
  const dataTrustColor =
    dataTrustQs === "VALID"
      ? "success"
      : dataTrustQs === "DEGRADED"
        ? "warning"
        : dataTrustQs === "INVALID"
          ? "error"
          : "default";

  /** pipeline-liveness stages만 표시 — 없는 단계는 "—" (추정 금지) */
  const pipelineCard = (label: string, marketCode: "UPBIT" | "KIWOOM", raw: unknown) => {
    const p = rec(raw);
    const stages = rec(p.stages);
    const firstZero = p.first_zero_stage ?? "—";
    const classification = String(
      p.classification ?? p.pipeline_health_state ?? "—",
    );
    const friendly = p.user_friendly_reason
      ? String(p.user_friendly_reason)
      : null;

    // UI 라벨 ↔ SoT funnel key (시장별). 없는 키는 "—"
    const pipelineSteps =
      marketCode === "UPBIT"
        ? [
            { label: "Signal", key: "ENTRY_EVALUATION" },
            { label: "Admission", key: "ENTRY_PASS" },
            { label: "Order", key: "ORDER" },
            { label: "Submitted", key: "ADMISSION" },
            { label: "Accepted", key: "ENTRY_PENDING" },
            { label: "Filled", key: "FILL" },
          ]
        : [
            { label: "Signal", key: "SIGNAL" },
            { label: "Admission", key: "ORDER_INTENT" },
            { label: "Order", key: "ORDER_CREATED" },
            { label: "Submitted", key: "ORDER_SUBMITTED" },
            { label: "Accepted", key: "ORDER_SUBMITTED" },
            { label: "Filled", key: "FILLED" },
          ];

    return (
      <Card size="small" title={`${label} 파이프라인`} style={{ height: "100%" }}>
        <Space wrap size={[8, 8]}>
          {pipelineSteps.map((step) => {
            const hasKey = Object.prototype.hasOwnProperty.call(stages, step.key);
            const val = hasKey ? stages[step.key] : undefined;
            return (
              <Tag key={`${step.label}-${step.key}`}>
                {step.label}: {hasKey ? String(val) : "—"}
              </Tag>
            );
          })}
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 0 }}>
          멈춤 지점: {String(firstZero)} · {classification}
          {friendly ? ` · ${friendly}` : ""}
        </Typography.Paragraph>
      </Card>
    );
  };

  const emptyHint =
    ownership === "AUTO"
      ? "오늘 자동매매 주문이 없습니다. 시장·필터를 확인해 주세요."
      : "현재 조건에 해당하는 주문이 없습니다.";

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap>
        <Radio.Group
          optionType="button"
          value={market}
          onChange={(e) => setMarket(e.target.value)}
          options={[
            { value: "ALL", label: "전체" },
            { value: "UPBIT", label: "업비트" },
            { value: "KIWOOM", label: "키움증권" },
          ]}
        />
        <Select
          value={ownership}
          onChange={setOwnership}
          style={{ width: 130 }}
          options={[
            { value: "AUTO", label: "자동매매" },
            { value: "MANUAL", label: "수동" },
            { value: "ALL", label: "전체 출처" },
            { value: "UNKNOWN", label: "확인 필요" },
          ]}
        />
        <Select
          allowClear
          showSearch
          placeholder="종목"
          style={{ width: 160 }}
          value={symbol}
          onChange={(v) => setSymbol(v)}
          options={[
            ...new Set(
              allRows
                .filter((r) => matchesMarket(r, market))
                .map((r) => String(r.symbol ?? ""))
                .filter(Boolean),
            ),
          ].map((s) => ({ value: s, label: s }))}
        />
        <Select
          value={statusFilter}
          onChange={setStatusFilter}
          style={{ width: 130 }}
          options={[
            { value: "ALL", label: "전체 상태" },
            { value: "FILLED", label: "체결" },
            { value: "SUBMITTED", label: "제출" },
            { value: "ACCEPTED", label: "접수" },
            { value: "CANCELLED", label: "취소" },
            { value: "REJECTED", label: "거부" },
          ]}
        />
        <Typography.Text type="secondary">기본: 오늘 · 자동매매</Typography.Text>
        {dataTrustLabel ? (
          <Tag color={dataTrustColor}>{dataTrustLabel}</Tag>
        ) : null}
      </Space>

      <Row gutter={[12, 12]}>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Card size="small">
            <Statistic title="오늘 매수" value={daySummary.buyCount} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Card size="small">
            <Statistic title="오늘 매도" value={daySummary.sellCount} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Card size="small">
            <Statistic title="체결" value={daySummary.filledCount} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Card size="small">
            <Statistic title="미체결" value={daySummary.openCount} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Card size="small">
            <Statistic title="취소" value={daySummary.cancelledCount} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Card size="small">
            <Statistic
              title="실현손익"
              value={realizedPnl ?? 0}
              precision={0}
              suffix="원"
              styles={{ content: { color: pnlColor(realizedPnl) } }}
              formatter={(v) =>
                Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })
              }
            />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Card size="small">
            <Statistic title="승/패" value={`${wins}/${losses}`} />
          </Card>
        </Col>
        <Col xs={12} sm={8} md={6} lg={3}>
          <Card size="small">
            <Statistic title="승률" value={formatPct(winRate)} />
          </Card>
        </Col>
      </Row>

      {(perfQ.isError || ordersQ.isError) && (
        <Alert
          type="warning"
          showIcon
          title="일부 데이터 조회 실패"
          description={
            ordersQ.error
              ? toApiError(ordersQ.error).message
              : perfQ.error
                ? toApiError(perfQ.error).message
                : undefined
          }
        />
      )}

      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <Card size="small" title="오늘 체결 흐름 (시간대)">
            {hourly.every((h) => h.buy === 0 && h.sell === 0) ? (
              <Empty description={emptyHint} />
            ) : (
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <LineChart data={hourly}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="label" tick={{ fontSize: 11 }} interval={2} />
                    <YAxis allowDecimals={false} width={32} />
                    <Tooltip
                      content={({ active, label }) => {
                        if (!active || label == null) return null;
                        const hour = String(label).slice(0, 2);
                        const tips = filledOrdersForTooltip(
                          filtered,
                          hour,
                          closedByOrderId,
                        );
                        return (
                          <Card size="small" style={{ maxWidth: 300 }}>
                            <Typography.Text strong>{label}</Typography.Text>
                            {tips.length === 0 ? (
                              <div>체결 없음</div>
                            ) : (
                              tips.map((t, i) => (
                                <div key={`${t.symbol}-${i}`}>
                                  {t.side} {t.symbol} · {t.price} × {t.qty}
                                  {t.exitReason ? ` · ${t.exitReason}` : ""}
                                  {t.pnl != null && t.side === "SELL"
                                    ? ` · PnL ${Number(t.pnl).toLocaleString("ko-KR")}`
                                    : ""}{" "}
                                  ({t.ownership})
                                </div>
                              ))
                            )}
                          </Card>
                        );
                      }}
                    />
                    <Legend />
                    <Line
                      type="monotone"
                      dataKey="buy"
                      name="매수"
                      stroke="#1677ff"
                      dot={false}
                      strokeWidth={2}
                    />
                    <Line
                      type="monotone"
                      dataKey="sell"
                      name="매도"
                      stroke="#cf1322"
                      dot={false}
                      strokeWidth={2}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card
            size="small"
            title="종목별 실현손익"
            extra={
              <Select
                size="small"
                value={pnlSort}
                onChange={setPnlSort}
                style={{ width: 120 }}
                options={[
                  { value: "profit", label: "이익 큰 순" },
                  { value: "loss", label: "손실 큰 순" },
                ]}
              />
            }
          >
            {symbolChart.length === 0 ? (
              <Empty description="오늘 청산 거래가 없습니다." />
            ) : (
              <div style={{ width: "100%", height: 240 }}>
                <ResponsiveContainer>
                  <BarChart data={symbolChart} layout="vertical" margin={{ left: 8 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis type="number" tick={{ fontSize: 11 }} />
                    <YAxis
                      type="category"
                      dataKey="symbol"
                      width={72}
                      tick={{ fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(v) => formatKrw(Number(v))}
                      labelFormatter={(l) => String(l)}
                    />
                    <Bar dataKey="net_pnl" name="실현손익">
                      {symbolChart.map((entry) => (
                        <Cell
                          key={entry.symbol}
                          fill={entry.net_pnl >= 0 ? "#3f8600" : "#cf1322"}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={[12, 12]}>
        <Col xs={24} md={12}>
          <Card size="small" title="매도 사유별 성과">
            <Table
              size="small"
              pagination={false}
              locale={{ emptyText: "오늘 청산 사유 집계가 없습니다." }}
              dataSource={exitRows}
              columns={[
                { title: "사유", dataIndex: "label", key: "label" },
                { title: "건수", dataIndex: "count", key: "count", width: 64 },
                { title: "승", dataIndex: "wins", key: "wins", width: 48 },
                { title: "패", dataIndex: "losses", key: "losses", width: 48 },
                {
                  title: "순손익",
                  dataIndex: "net",
                  key: "net",
                  render: (v: number) => (
                    <span style={{ color: pnlColor(v) }}>{formatKrw(v)}</span>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Space orientation="vertical" style={{ width: "100%" }} size={12}>
            {(market === "ALL" || market === "UPBIT") &&
              pipelineCard("업비트", "UPBIT", pipeUpbitQ.data)}
            {(market === "ALL" || market === "KIWOOM") &&
              pipelineCard("키움", "KIWOOM", pipeKiwoomQ.data)}
            <Typography.Text type="secondary">
              파이프라인 SoT: pipeline-liveness (별도 추정 집계 없음)
            </Typography.Text>
          </Space>
        </Col>
      </Row>

      <Card size="small" title="오늘 주문 목록">
        <Table
          size="small"
          loading={ordersQ.isLoading}
          rowKey={(r) => String(r.order_id ?? r.id)}
          dataSource={filtered}
          locale={{ emptyText: emptyHint }}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          scroll={{ x: 960 }}
          columns={[
            {
              title: "시간",
              key: "time",
              width: 160,
              render: (_: unknown, row: OrderRow) =>
                cell(row.filled_at ?? row.created_at),
            },
            {
              title: "시장",
              dataIndex: "broker_code",
              width: 88,
              render: (v: unknown, row: OrderRow) =>
                cell(v ?? row.exchange_code),
            },
            { title: "종목", dataIndex: "symbol", width: 100 },
            {
              title: "자동/수동",
              key: "own",
              width: 88,
              render: (_: unknown, row: OrderRow) => {
                const h = resolveOrderTradingKind(row);
                return (
                  <Tag
                    color={
                      h.kind === "AUTO"
                        ? "processing"
                        : h.kind === "MANUAL"
                          ? "default"
                          : "warning"
                    }
                  >
                    {h.labelKo}
                  </Tag>
                );
              },
            },
            {
              title: "매수/매도",
              dataIndex: "side_code",
              width: 80,
              render: (v: unknown) => sideLabelKo(v == null ? null : String(v)),
            },
            {
              title: "상태",
              dataIndex: "status_code",
              width: 88,
              render: (v: unknown) =>
                orderStatusLabelKo(v == null ? null : String(v)),
            },
            {
              title: "수량",
              key: "qty",
              width: 88,
              render: (_: unknown, row: OrderRow) =>
                cell(row.filled_quantity ?? row.order_quantity),
            },
            {
              title: "체결가",
              key: "px",
              width: 96,
              render: (_: unknown, row: OrderRow) =>
                cell(row.average_fill_price ?? row.order_price),
            },
            {
              title: "진입/청산 사유",
              key: "reason",
              ellipsis: true,
              render: (_: unknown, row: OrderRow) => {
                const id = Number(row.order_id ?? row.id);
                const trip = closedByOrderId.get(id);
                if (!trip) return "—";
                return String(
                  trip.exit_reason_label_ko ?? trip.exit_reason_category ?? "—",
                );
              },
            },
            {
              title: "실현손익",
              key: "pnl",
              width: 110,
              render: (_: unknown, row: OrderRow) => {
                const id = Number(row.order_id ?? row.id);
                const trip = closedByOrderId.get(id);
                if (!trip) return "—";
                const net = numOrNull(trip.net_pnl);
                return (
                  <span style={{ color: pnlColor(net) }}>{formatKrw(net)}</span>
                );
              },
            },
            {
              title: "상세",
              key: "detail",
              width: 72,
              fixed: "right",
              render: (_: unknown, row: OrderRow) => (
                <a
                  onClick={() =>
                    onOpenDetail(Number(row.order_id ?? row.id))
                  }
                >
                  보기
                </a>
              ),
            },
          ]}
        />
        <Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>
          실현손익·청산 사유 SoT:{" "}
          <code>autotrading-performance</code> (STRATEGY_OWNED binding).{" "}
          <Link href={adminRoutes.autotradingProcess}>프로세스·버전</Link>
        </Typography.Paragraph>
      </Card>
    </Space>
  );
}
