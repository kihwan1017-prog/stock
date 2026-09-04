"use client";

/**
 * 종목별 AUTO 거래 Drawer — 기간 KPI + 일별 + 건별 상세.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Col,
  Drawer,
  Empty,
  Grid,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

import {
  durationLabel,
  formatKrw,
  formatPct,
  pnlColor,
  type BrokerFilter,
  type PeriodFilter,
} from "./autoTradingPerformanceHelpers";

function rec(v: unknown): Record<string, unknown> {
  return asRecord(v) ?? {};
}

function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

type Props = {
  open: boolean;
  onClose: () => void;
  symbol: string | null;
  broker: BrokerFilter;
  period: PeriodFilter;
  startDate?: string | null;
  endDate?: string | null;
  userBrokerAccountId?: number | null;
  symbolName?: string | null;
};

export function SymbolPerformanceDrawer({
  open,
  onClose,
  symbol,
  broker,
  period,
  startDate = null,
  endDate = null,
  userBrokerAccountId = null,
  symbolName = null,
}: Props) {
  const screens = Grid.useBreakpoint();
  const width = screens.md ? 820 : "100%";

  const detailQ = useQuery({
    queryKey: queryKeys.admin.autotradingSymbolDetail({
      symbol: symbol ?? "",
      broker,
      period,
      startDate,
      endDate,
      ubaId: userBrokerAccountId,
    }),
    queryFn: () =>
      adminApi.getAdminAutotradingSymbolDetail({
        symbol: String(symbol),
        broker,
        period,
        start_date: startDate ?? undefined,
        end_date: endDate ?? undefined,
        user_broker_account_id: userBrokerAccountId ?? undefined,
      }),
    enabled: open && Boolean(symbol),
    staleTime: 30_000,
  });

  const data = rec(detailQ.data);
  const totals = rec(data.totals);
  const window = rec(data.period_window);
  const periodLabel = String(
    window.label ??
      `${window.start_date ?? "—"} ~ ${window.end_date ?? "—"}`,
  );
  const daily = extractRows(data.daily).map((r) => rec(r));
  const trades = extractRows(data.trades).map((r) => rec(r));
  const titleName = symbolName ? ` · ${symbolName}` : "";

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={width}
      destroyOnHidden
      title={`${symbol ?? ""}${titleName} 거래 상세`}
    >
      {!symbol ? (
        <Empty description="종목을 선택하세요." />
      ) : detailQ.isLoading ? (
        <Typography.Text type="secondary">불러오는 중…</Typography.Text>
      ) : detailQ.isError ? (
        <Alert
          type="error"
          showIcon
          title="종목 상세를 불러오지 못했습니다."
          description={toApiError(detailQ.error).message}
        />
      ) : trades.length === 0 ? (
        <Empty description="선택 기간에 AUTO 거래가 없습니다." />
      ) : (
        <Space orientation="vertical" size={16} style={{ width: "100%" }}>
          <Typography.Text type="secondary">
            조회기간: {periodLabel} (KST)
          </Typography.Text>
          <Row gutter={[12, 12]}>
            <Col xs={12} sm={8}>
              <Statistic title="총 매수" value={Number(totals.buy_count ?? 0)} />
            </Col>
            <Col xs={12} sm={8}>
              <Statistic title="총 매도" value={Number(totals.sell_count ?? 0)} />
            </Col>
            <Col xs={12} sm={8}>
              <Statistic
                title="완료 거래"
                value={Number(totals.round_trip_count ?? 0)}
              />
            </Col>
            <Col xs={12} sm={8}>
              <Statistic
                title="Gross"
                value={num(totals.gross_pnl) ?? 0}
                precision={0}
                suffix="원"
                styles={{ content: { color: pnlColor(num(totals.gross_pnl)) } }}
              />
            </Col>
            <Col xs={12} sm={8}>
              <Statistic
                title="Fee"
                value={num(totals.fees) ?? 0}
                precision={0}
                suffix="원"
              />
            </Col>
            <Col xs={12} sm={8}>
              <Statistic
                title="Net"
                value={num(totals.net_pnl) ?? 0}
                precision={0}
                suffix="원"
                styles={{ content: { color: pnlColor(num(totals.net_pnl)) } }}
              />
            </Col>
            <Col xs={12} sm={8}>
              <Statistic
                title="승률"
                value={
                  num(totals.win_rate_pct) != null
                    ? formatPct(num(totals.win_rate_pct))
                    : "—"
                }
              />
            </Col>
          </Row>

          <Typography.Title level={5} style={{ margin: 0 }}>
            일자별 성과
          </Typography.Title>
          <Table
            size="small"
            pagination={false}
            scroll={{ x: 720 }}
            rowKey={(r) => String(rec(r).date)}
            dataSource={daily}
            columns={[
              { title: "날짜", dataIndex: "date", width: 110 },
              { title: "매수", dataIndex: "buy_count", width: 64 },
              { title: "매도", dataIndex: "sell_count", width: 64 },
              { title: "완료", dataIndex: "round_trip_count", width: 64 },
              {
                title: "Gross",
                dataIndex: "gross_pnl",
                render: (v) => formatKrw(num(v), 0),
              },
              {
                title: "Fee",
                dataIndex: "fees",
                render: (v) => formatKrw(num(v), 0),
              },
              {
                title: "Net",
                dataIndex: "net_pnl",
                render: (v) => (
                  <span style={{ color: pnlColor(num(v)) }}>
                    {formatKrw(num(v), 0)}
                  </span>
                ),
              },
              {
                title: "승률",
                dataIndex: "win_rate_pct",
                render: (v) => formatPct(num(v)),
              },
            ]}
          />

          <Typography.Title level={5} style={{ margin: 0 }}>
            건별 거래
          </Typography.Title>
          <Table
            size="small"
            pagination={{ pageSize: 8 }}
            scroll={{ x: 1400 }}
            rowKey={(r) => String(rec(r).binding_id ?? rec(r).closed_at)}
            dataSource={trades}
            columns={[
              {
                title: "청산시각",
                dataIndex: "closed_at",
                width: 160,
                ellipsis: true,
              },
              {
                title: "방향",
                width: 72,
                render: () => <Tag>SELL</Tag>,
              },
              {
                title: "Entry",
                dataIndex: "entry_price",
                width: 80,
              },
              {
                title: "Exit",
                dataIndex: "exit_price",
                width: 80,
              },
              { title: "Qty", dataIndex: "quantity", width: 72 },
              {
                title: "Gross",
                dataIndex: "gross_pnl",
                render: (v) => formatKrw(num(v), 2),
              },
              {
                title: "Fee",
                dataIndex: "fees",
                render: (v) => formatKrw(num(v), 2),
              },
              {
                title: "Net",
                dataIndex: "net_pnl",
                render: (v) => (
                  <span style={{ color: pnlColor(num(v)) }}>
                    {formatKrw(num(v), 2)}
                  </span>
                ),
              },
              {
                title: "수익률",
                dataIndex: "return_pct",
                render: (v) => formatPct(num(v)),
              },
              {
                title: "보유",
                dataIndex: "duration_sec",
                render: (v) => durationLabel(num(v) ?? undefined),
              },
              {
                title: "Exit Reason",
                dataIndex: "exit_reason_label_ko",
                ellipsis: true,
              },
              {
                title: "order",
                dataIndex: "exit_order_id",
                width: 80,
              },
            ]}
          />
        </Space>
      )}
    </Drawer>
  );
}
