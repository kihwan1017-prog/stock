"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo } from "react";

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { userRoutes } from "@/config/routes";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { useMyPaperAccountId } from "@/features/user/hooks/useMyPaperAccountId";
import {
  computeHoldingWeights,
  computeReturnRate,
} from "@/features/user/portfolio/holdingMetrics";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";


const CHART_COLORS = [
  "#1677ff",
  "#52c41a",
  "#faad14",
  "#eb2f96",
  "#722ed1",
  "#13c2c2",
  "#fa541c",
  "#2f54eb",
];

function formatNumber(value: unknown, suffix = ""): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const num = Number(value);
  if (Number.isFinite(num)) {
    return `${num.toLocaleString("ko-KR")}${suffix}`;
  }
  return `${cell(value)}${suffix}`;
}

function formatPct(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const num = Number(value);
  if (Number.isFinite(num)) {
    return `${num.toFixed(2)}%`;
  }
  return cell(value);
}

function pnlColor(value: unknown): string | undefined {
  const num = Number(value);
  if (!Number.isFinite(num) || num === 0) return undefined;
  return num < 0 ? "#cf1322" : "#3f8600";
}

function tableRowKey(row: Record<string, unknown>, fields: string[]): string {
  for (const field of fields) {
    const value = row[field];
    if (value !== null && value !== undefined && value !== "") {
      return String(value);
    }
  }
  try {
    return JSON.stringify(row);
  } catch {
    return "unknown-row";
  }
}

function toNumber(value: unknown): number {
  const num = Number(value);
  return Number.isFinite(num) ? num : 0;
}

interface HoldingRow {
  key: string;
  exchange_code: string;
  symbol: string;
  quantity: number;
  average_entry_price: number;
  current_price: number | null;
  cost_value: number;
  market_value: number;
  unrealized_pnl: number;
  return_rate: number;
  weight: number;
  price_missing: boolean;
}

/** 비중 도넛 차트 (외부 차트 라이브러리 없이 SVG) */
function AllocationDonut({
  slices,
}: {
  slices: { label: string; weight: number; color: string }[];
}) {
  const size = 200;
  const stroke = 28;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const usable = slices.filter((s) => s.weight > 0);
  const total = usable.reduce((sum, s) => sum + s.weight, 0);

  if (total <= 0) {
    return (
      <Typography.Text type="secondary">비중 데이터가 없습니다</Typography.Text>
    );
  }

  const segments = usable.reduce<
    { label: string; color: string; dash: number; offset: number }[]
  >((acc, slice) => {
    const portion = slice.weight / total;
    const dash = portion * circumference;
    const prevOffset = acc.length ? acc[acc.length - 1].offset + acc[acc.length - 1].dash : 0;
    acc.push({
      label: slice.label,
      color: slice.color,
      dash,
      offset: prevOffset,
    });
    return acc;
  }, []);

  return (
    <div style={{ display: "flex", gap: 24, alignItems: "center", flexWrap: "wrap" }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--ant-color-fill-secondary, #f0f0f0)"
          strokeWidth={stroke}
        />
        {segments.map((segment) => (
          <circle
            key={segment.label}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={segment.color}
            strokeWidth={stroke}
            strokeDasharray={`${segment.dash} ${circumference - segment.dash}`}
            strokeDashoffset={-segment.offset}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        ))}
      </svg>
      <Space orientation="vertical" size={4}>
        {usable.map((slice) => (
          <Space key={slice.label} size={8}>
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: 2,
                background: slice.color,
                display: "inline-block",
              }}
            />
            <Typography.Text style={{ fontSize: 12 }}>
              {slice.label} · {slice.weight.toFixed(1)}%
            </Typography.Text>
          </Space>
        ))}
      </Space>
    </div>
  );
}

export default function UserPortfolioPage() {
  const { accountId } = useMyPaperAccountId();

  const kpisQuery = useQuery({
    queryKey: queryKeys.user.investmentKpis(accountId ?? 0),
    queryFn: () =>
      userApi.getInvestmentKpis({
        account_id: accountId as number,
        market_code: "KRX",
        mode_code: "PAPER",
      }),
    enabled: accountId != null,
    refetchInterval: 30_000,
  });

  const accountQuery = useQuery({
    queryKey: queryKeys.user.paperAccount(accountId ?? 0),
    queryFn: () => userApi.getPaperAccount(accountId as number),
    enabled: accountId != null,
  });

  const positionsQuery = useQuery({
    queryKey: queryKeys.user.paperPositions(accountId ?? 0),
    queryFn: () => userApi.getPaperPositions(accountId as number),
    enabled: accountId != null,
    refetchInterval: 30_000,
  });

  const ordersQuery = useQuery({
    queryKey: [...queryKeys.user.orders(), "portfolio", { limit: 30, account_id: accountId }],
    queryFn: () =>
      userApi.listOrders({
        account_id: accountId as number,
        limit: 30,
        offset: 0,
      }),
    enabled: accountId != null,
  });

  const executionsQuery = useQuery({
    queryKey: [...queryKeys.user.executions(), "portfolio", { limit: 30 }],
    queryFn: () => userApi.listExecutions({ limit: 30 }),
  });

  const paperOrdersQuery = useQuery({
    queryKey: [...queryKeys.user.paperOrders(), "portfolio"],
    queryFn: userApi.listPaperOrders,
  });

  const rawPositions = useMemo(() => {
    const data = positionsQuery.data;
    if (Array.isArray(data)) {
      return data.filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      );
    }
    return extractRows(data);
  }, [positionsQuery.data]);

  const priceQueries = useQueries({
    queries: rawPositions.map((row) => {
      const exchange = String(row.exchange_code ?? "KRX");
      const symbol = String(row.symbol ?? "");
      return {
        queryKey: queryKeys.user.latestPrice(exchange, symbol),
        queryFn: () => userApi.getLatestPrice(exchange, symbol),
        enabled: Boolean(symbol),
        staleTime: 60_000,
        retry: false,
      };
    }),
  });

  const priceUpdatedAtKey = priceQueries.map((q) => q.dataUpdatedAt).join("|");

  const priceBySymbol = useMemo(() => {
    const map = new Map<string, number>();
    rawPositions.forEach((row, index) => {
      const exchange = String(row.exchange_code ?? "KRX");
      const symbol = String(row.symbol ?? "");
      const priceData = asRecord(priceQueries[index]?.data);
      const close = priceData
        ? toNumber(priceData.close_price ?? priceData.close)
        : NaN;
      if (symbol && Number.isFinite(close) && close > 0) {
        map.set(`${exchange}:${symbol}`, close);
      }
    });
    return map;
    // priceQueries 배열 참조 대신 dataUpdatedAt 키로 갱신
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawPositions, priceUpdatedAtKey]);

  const holdings: HoldingRow[] = useMemo(() => {
    const rows: HoldingRow[] = rawPositions.map((row) => {
      const exchange = String(row.exchange_code ?? "KRX");
      const symbol = String(row.symbol ?? "");
      const quantity = toNumber(row.quantity);
      const average = toNumber(row.average_entry_price);
      const cost = quantity * average;
      const close = priceBySymbol.get(`${exchange}:${symbol}`);
      const hasPrice = close !== undefined;
      const current = hasPrice ? close : average;
      const market = quantity * current;
      const unrealized = market - cost;

      return {
        key: `${exchange}:${symbol}`,
        exchange_code: exchange,
        symbol,
        quantity,
        average_entry_price: average,
        current_price: hasPrice ? close : null,
        cost_value: cost,
        market_value: market,
        unrealized_pnl: unrealized,
        return_rate: computeReturnRate(market, cost),
        weight: 0,
        price_missing: !hasPrice,
      };
    });

    const weights = computeHoldingWeights(rows.map((row) => row.market_value));
    return rows.map((row, index) => ({
      ...row,
      weight: weights[index] ?? 0,
    }));
  }, [rawPositions, priceBySymbol]);

  const summary = asRecord(kpisQuery.data);
  const kpis = asRecord(summary?.kpis);
  const account = asRecord(accountQuery.data);

  const totalMarketValue = holdings.reduce(
    (sum, row) => sum + row.market_value,
    0,
  );
  const totalUnrealized = holdings.reduce(
    (sum, row) => sum + row.unrealized_pnl,
    0,
  );
  const totalCost = holdings.reduce((sum, row) => sum + row.cost_value, 0);
  const portfolioReturn =
    totalCost > 0 ? (totalUnrealized / totalCost) * 100 : 0;

  const chartSlices = holdings
    .filter((row) => row.weight > 0)
    .map((row, index) => ({
      label: row.symbol,
      weight: row.weight,
      color: CHART_COLORS[index % CHART_COLORS.length],
    }));

  // 거래내역: paper-orders 우선, 없으면 trading orders + executions
  const paperOrderRows = extractRows(paperOrdersQuery.data);
  const orderRows = extractRows(ordersQuery.data);
  const executionRows = extractRows(executionsQuery.data);

  const tradeRows =
    paperOrderRows.length > 0
      ? paperOrderRows.slice(0, 30).map((row) => ({
          source: "paper",
          id: row.paper_order_id ?? row.order_id,
          symbol: row.symbol,
          side: row.side,
          quantity: row.quantity ?? row.requested_quantity ?? row.filled_quantity,
          price: row.price ?? row.average_fill_price ?? row.fill_price,
          status: row.status_code ?? row.status,
          at: row.created_at ?? row.updated_at,
        }))
      : [
          ...orderRows.slice(0, 15).map((row) => ({
            source: "order",
            id: row.order_id,
            symbol: row.symbol,
            side: row.side,
            quantity: row.quantity ?? row.order_quantity,
            price: row.price,
            status: row.status_code,
            at: row.created_at,
          })),
          ...executionRows.slice(0, 15).map((row) => ({
            source: "execution",
            id: row.execution_id ?? row.trading_execution_id,
            symbol: row.symbol,
            side: row.side,
            quantity: row.quantity ?? row.execution_quantity,
            price: row.price,
            status: "FILLED",
            at: row.executed_at ?? row.created_at,
          })),
        ];

  const pricesLoading = priceQueries.some((q) => q.isLoading);
  const anyPriceError = priceQueries.some((q) => q.isError);

  return (
    <UserPageShell
      title="포트폴리오"
      description={`보유 · 수익률 · 평가 · 비중 · 거래내역 · Paper #${accountId ?? "…"} · STEP43`}
      extra={
        <Space wrap>
          <Button size="small">
            <Link href={userRoutes.dashboard}>Dashboard</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.trading}>매매</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.trades}>거래내역</Link>
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap size={8}>
          <Tag>Mode: PAPER</Tag>
          <Tag>Account: #{accountId ?? "…"}</Tag>
          <Tag>평가: {cell(kpis?.valuation_mode ?? "…")}</Tag>
          <Tag>종목 {holdings.length}개</Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            KPI `/dashboard/admin-summary` · 보유 `/paper-accounts/{"{id}"}/positions` ·
            시세 `/prices/latest`
          </Typography.Text>
        </Space>

        {kpisQuery.error ? (
          <Alert
            type="error"
            showIcon
            title="요약 조회 실패"
            description={toApiError(kpisQuery.error).message}
          />
        ) : null}

        {/* 요약 KPI */}
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={kpisQuery.isLoading}>
              <Statistic
                title="총 자산"
                value={formatNumber(kpis?.total_equity)}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={positionsQuery.isLoading || pricesLoading}>
              <Statistic
                title="평가 금액"
                value={formatNumber(
                  kpis?.position_market_value ?? totalMarketValue,
                )}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={positionsQuery.isLoading || pricesLoading}>
              <Statistic
                title="종목 수익률(합산)"
                value={formatPct(
                  Number.isFinite(portfolioReturn)
                    ? portfolioReturn
                    : kpis?.today_return_rate,
                )}
                styles={{ content: { color: pnlColor(totalUnrealized) } }}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                평가손익 {formatNumber(totalUnrealized || kpis?.unrealized_pnl)}
              </Typography.Text>
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={accountQuery.isLoading || kpisQuery.isLoading}>
              <Statistic
                title="예수금"
                value={formatNumber(
                  account?.available_cash ?? kpis?.available_cash,
                )}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                실현손익 {formatNumber(kpis?.realized_pnl)}
              </Typography.Text>
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          {/* 보유 비중 */}
          <Col xs={24} lg={10}>
            <Card
              title="보유 비중"
              size="small"
              loading={positionsQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  평가금액 기준
                </Typography.Text>
              }
            >
              <AllocationDonut slices={chartSlices} />
              {holdings.length > 0 ? (
                <Space
                  orientation="vertical"
                  size={8}
                  style={{ width: "100%", marginTop: 16 }}
                >
                  {holdings.map((row, index) => (
                    <div key={row.key}>
                      <FlexLabel
                        left={row.symbol}
                        right={formatPct(row.weight)}
                      />
                      <Progress
                        percent={Number(row.weight.toFixed(1))}
                        showInfo={false}
                        size="small"
                        strokeColor={
                          CHART_COLORS[index % CHART_COLORS.length]
                        }
                      />
                    </div>
                  ))}
                </Space>
              ) : null}
            </Card>
          </Col>

          {/* 보유 종목 + 종목별 수익률 */}
          <Col xs={24} lg={14}>
            <Card
              title="보유 종목 · 종목별 수익률"
              size="small"
              loading={positionsQuery.isLoading || pricesLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /paper-accounts/{accountId ?? "…"}/positions
                </Typography.Text>
              }
            >
              {positionsQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(positionsQuery.error).message}
                />
              ) : (
                <>
                  {anyPriceError ? (
                    <Alert
                      type="warning"
                      showIcon
                      style={{ marginBottom: 12 }}
                      title="일부 종목 최신가가 없어 평단으로 평가했습니다"
                    />
                  ) : null}
                  <Table
                    size="small"
                    pagination={false}
                    rowKey={(row) => row.key}
                    dataSource={holdings}
                    scroll={{ x: 720 }}
                    locale={{ emptyText: "보유 종목 없음" }}
                    columns={[
                      { title: "심볼", dataIndex: "symbol", fixed: "left" },
                      {
                        title: "거래소",
                        dataIndex: "exchange_code",
                        width: 80,
                      },
                      {
                        title: "수량",
                        dataIndex: "quantity",
                        render: (v) => formatNumber(v),
                      },
                      {
                        title: "평단",
                        dataIndex: "average_entry_price",
                        render: (v) => formatNumber(v),
                      },
                      {
                        title: "현재가",
                        dataIndex: "current_price",
                        render: (v, row) =>
                          row.price_missing ? (
                            <Typography.Text type="secondary">
                              평단
                            </Typography.Text>
                          ) : (
                            formatNumber(v)
                          ),
                      },
                      {
                        title: "평가 금액",
                        dataIndex: "market_value",
                        render: (v) => formatNumber(v),
                      },
                      {
                        title: "수익률",
                        dataIndex: "return_rate",
                        render: (v) => (
                          <span style={{ color: pnlColor(v) }}>
                            {formatPct(v)}
                          </span>
                        ),
                      },
                      {
                        title: "비중",
                        dataIndex: "weight",
                        render: (v) => formatPct(v),
                      },
                    ]}
                  />
                </>
              )}
            </Card>
          </Col>
        </Row>

        {/* 거래 내역 */}
        <Card
          title="거래 내역"
          size="small"
          loading={
            paperOrdersQuery.isLoading ||
            ordersQuery.isLoading ||
            executionsQuery.isLoading
          }
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /paper-orders · /orders · /executions
            </Typography.Text>
          }
        >
          {(paperOrdersQuery.error ||
            ordersQuery.error ||
            executionsQuery.error) &&
          tradeRows.length === 0 ? (
            <Alert
              type="error"
              showIcon
              title={
                toApiError(
                  paperOrdersQuery.error ??
                    ordersQuery.error ??
                    executionsQuery.error!,
                ).message
              }
            />
          ) : (
            <Table
              size="small"
              pagination={{ pageSize: 10 }}
              rowKey={(row) =>
                tableRowKey(
                  row as unknown as Record<string, unknown>,
                  ["source", "id", "symbol", "at"],
                )
              }
              dataSource={tradeRows}
              locale={{ emptyText: "거래내역 없음" }}
              columns={[
                {
                  title: "구분",
                  dataIndex: "source",
                  width: 90,
                  render: (v) => <Tag>{cell(v)}</Tag>,
                },
                {
                  title: "ID",
                  dataIndex: "id",
                  width: 80,
                  render: cell,
                },
                { title: "심볼", dataIndex: "symbol", render: cell },
                { title: "측", dataIndex: "side", width: 70, render: cell },
                {
                  title: "수량",
                  dataIndex: "quantity",
                  render: (v) => formatNumber(v),
                },
                {
                  title: "가격",
                  dataIndex: "price",
                  render: (v) => formatNumber(v),
                },
                {
                  title: "상태",
                  dataIndex: "status",
                  render: (v) => <Tag>{cell(v)}</Tag>,
                },
                {
                  title: "시각",
                  dataIndex: "at",
                  render: cell,
                },
              ]}
            />
          )}
        </Card>

        {/* 자산 변화 차트 — API 없음 */}
        <Card
          title="자산 변화 차트"
          size="small"
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              TODO
            </Typography.Text>
          }
        >
          {/* TODO: GET /api/v1/paper-accounts/{id}/equity-history — NAV/총자산 시계열 */}
          <UnimplementedNotice
            feature="자산 변화 차트"
            reason="일별 총자산(equity/NAV) 히스토리 API가 Backend에 없습니다. 추가 후 라인 차트를 연결합니다. (백테스트 equity_curve는 포트폴리오 실계좌와 무관하여 사용하지 않습니다.)"
            relatedApis={[
              "TODO: GET /api/v1/paper-accounts/{id}/equity-history",
              "참고(미사용): GET /api/v1/backtest-runs/{id} equity_curve",
            ]}
          />
        </Card>
      </Space>
    </UserPageShell>
  );
}

function FlexLabel({ left, right }: { left: string; right: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        marginBottom: 2,
      }}
    >
      <Typography.Text style={{ fontSize: 12 }}>{left}</Typography.Text>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {right}
      </Typography.Text>
    </div>
  );
}
