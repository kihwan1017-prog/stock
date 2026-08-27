"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import {
  Alert,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Empty,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Statistic,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { Dayjs } from "dayjs";
import dayjs from "dayjs";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell } from "@/features/admin/utils/dataHelpers";
import { adminRoutes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type MarketKey = "UPBIT" | "KIWOOM";
type TimeframeKey = "day" | "minute";

const MARKET_API: Record<MarketKey, string> = {
  UPBIT: "UPBIT",
  KIWOOM: "KIWOOM",
};

const PERIOD_PRESETS = [
  { label: "7일", days: 7 },
  { label: "1개월", days: 30 },
  { label: "3개월", days: 90 },
  { label: "6개월", days: 180 },
  { label: "1년", days: 365 },
] as const;

const YEAR_OPTIONS = [2024, 2025, 2026];

function parseMarketKey(raw: string | null): MarketKey {
  const v = (raw ?? "").toUpperCase();
  if (v === "KIWOOM" || v === "KRX") return "KIWOOM";
  return "UPBIT";
}

/** Recharts custom shape — OHLC Candlestick (심지+몸통) */
function CandlestickBar(props: Record<string, unknown>) {
  const x = Number(props.x ?? 0);
  const width = Number(props.width ?? 0);
  const payload = props.payload as
    | { open: number; high: number; low: number; close: number }
    | undefined;
  const yAxis = props.yAxis as { scale?: (v: number) => number } | undefined;
  if (!payload || width <= 0 || !yAxis?.scale) return null;

  const openY = yAxis.scale(payload.open);
  const closeY = yAxis.scale(payload.close);
  const highY = yAxis.scale(payload.high);
  const lowY = yAxis.scale(payload.low);
  const isUp = payload.close >= payload.open;
  const color = isUp ? "#16a34a" : "#dc2626";
  const bodyTop = Math.min(openY, closeY);
  const bodyHeight = Math.max(Math.abs(closeY - openY), 1);
  const cx = x + width / 2;
  const wickWidth = Math.max(1, Math.min(2, width * 0.15));
  const bodyWidth = Math.max(2, width * 0.55);
  const bodyX = x + (width - bodyWidth) / 2;

  return (
    <g>
      <line
        x1={cx}
        x2={cx}
        y1={highY}
        y2={lowY}
        stroke={color}
        strokeWidth={wickWidth}
      />
      <rect
        x={bodyX}
        y={bodyTop}
        width={bodyWidth}
        height={bodyHeight}
        fill={isUp ? color : "#fff"}
        stroke={color}
        strokeWidth={1}
      />
    </g>
  );
}

function CandleTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: Record<string, unknown> }>;
}) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload ?? {};
  return (
    <Card size="small" style={{ minWidth: 180 }}>
      <Typography.Text strong>{String(row.dateLabel ?? "")}</Typography.Text>
      <Descriptions column={1} size="small" style={{ marginTop: 8 }}>
        <Descriptions.Item label="시가">{cell(row.open)}</Descriptions.Item>
        <Descriptions.Item label="고가">{cell(row.high)}</Descriptions.Item>
        <Descriptions.Item label="저가">{cell(row.low)}</Descriptions.Item>
        <Descriptions.Item label="종가">{cell(row.close)}</Descriptions.Item>
        <Descriptions.Item label="거래량">{cell(row.volume)}</Descriptions.Item>
        <Descriptions.Item label="거래대금">{cell(row.trade_amount)}</Descriptions.Item>
      </Descriptions>
    </Card>
  );
}

export function MarketDataExplorerView() {
  const searchParams = useSearchParams();
  const initialMarket = parseMarketKey(searchParams.get("market"));
  const initialSymbol = searchParams.get("symbol")?.toUpperCase() || undefined;
  const initialDate = searchParams.get("date");

  const [market, setMarket] = useState<MarketKey>(initialMarket);
  const [symbol, setSymbol] = useState<string | undefined>(initialSymbol);
  const [timeframe, setTimeframe] = useState<TimeframeKey>("day");
  const [periodDays, setPeriodDays] = useState(30);
  const [year, setYear] = useState<number | null>(null);
  const [customRange, setCustomRange] = useState<[Dayjs, Dayjs] | null>(() => {
    if (!initialDate) return null;
    const d = dayjs(initialDate);
    if (!d.isValid()) return null;
    return [d.subtract(14, "day"), d.add(1, "day")];
  });
  const [activeTab, setActiveTab] = useState("chart");

  const range = useMemo(() => {
    if (year) {
      return { from: `${year}-01-01`, to: `${year}-12-31` };
    }
    if (customRange) {
      return {
        from: customRange[0].format("YYYY-MM-DD"),
        to: customRange[1].format("YYYY-MM-DD"),
      };
    }
    const to = dayjs();
    const from = to.subtract(periodDays, "day");
    return { from: from.format("YYYY-MM-DD"), to: to.format("YYYY-MM-DD") };
  }, [year, customRange, periodDays]);

  const symbolsQuery = useQuery({
    queryKey: queryKeys.admin.marketDataSymbols(market),
    queryFn: () => adminApi.getMarketDataSymbols({ market: MARKET_API[market], limit: 500 }),
  });

  const symbolOptions = useMemo(() => {
    const body = symbolsQuery.data as { items?: Record<string, unknown>[] } | undefined;
    const items = body?.items ?? [];
    return items.map((item) => ({
      value: String(item.symbol ?? ""),
      label: `${item.symbol ?? ""} ${item.name ?? ""}`.trim(),
    }));
  }, [symbolsQuery.data]);

  const candlesQuery = useQuery({
    queryKey: queryKeys.admin.marketDataCandles({
      market,
      symbol,
      timeframe,
      ...range,
      year,
    }),
    queryFn: () =>
      adminApi.getMarketDataCandles({
        market: MARKET_API[market],
        symbol: symbol ?? "",
        timeframe,
        from: range.from,
        to: range.to,
        year: year ?? undefined,
        limit: 500,
      }),
    enabled: Boolean(symbol) && activeTab === "chart",
  });

  const symbolInfoQuery = useQuery({
    queryKey: queryKeys.admin.marketDataSymbolInfo(market, symbol ?? ""),
    queryFn: () =>
      adminApi.getMarketDataSymbolInfo({
        market: MARKET_API[market],
        symbol: symbol ?? "",
      }),
    enabled: Boolean(symbol),
  });

  const statusQuery = useQuery({
    queryKey: queryKeys.admin.marketDataStatus(),
    queryFn: adminApi.getMarketDataStatus,
    enabled: activeTab === "collection",
  });

  const qualityQuery = useQuery({
    queryKey: queryKeys.admin.marketDataQuality(market),
    queryFn: () => adminApi.getMarketDataQuality({ market: MARKET_API[market] }),
    enabled: activeTab === "quality",
  });

  const candleBody = candlesQuery.data as {
    items?: Record<string, unknown>[];
    row_count?: number;
    first_date?: string;
    last_date?: string;
    policy_message?: string;
  };

  const chartRows = useMemo(() => {
    const items = candleBody?.items ?? [];
    return items.map((row) => {
      const dateRaw = row.candle_date ?? row.candle_at;
      const dateLabel = dateRaw ? dayjs(String(dateRaw)).format("YYYY-MM-DD") : "";
      const open = Number(row.open_price ?? 0);
      const close = Number(row.close_price ?? 0);
      const high = Number(row.high_price ?? 0);
      const low = Number(row.low_price ?? 0);
      return {
        dateLabel,
        open,
        close,
        high,
        low,
        volume: Number(row.volume ?? 0),
        trade_amount: row.trade_amount,
        // Candlestick custom shape가 high/low 스케일을 쓰도록 값 전달
        candle: [low, open, close, high] as [number, number, number, number],
      };
    });
  }, [candleBody?.items]);

  const qualityItems =
    ((qualityQuery.data as { items?: Record<string, unknown>[] })?.items ?? []);

  return (
    <AdminPageShell
      title="시장 데이터"
      description="UPBIT/KIWOOM 원천 시세 조회 · 수집 현황 · 데이터 품질 (자동매매 제어 없음)"
      extra={
        <Space wrap>
          <Typography.Link href={adminRoutes.upbitMarkets}>업비트 시세(레거시)</Typography.Link>
          <Typography.Link href="/user/markets/crypto">User Crypto</Typography.Link>
          <Typography.Link href="/user/markets/stocks">User Stocks</Typography.Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Segmented<MarketKey>
          options={[
            { label: "UPBIT", value: "UPBIT" },
            { label: "KIWOOM", value: "KIWOOM" },
          ]}
          value={market}
          onChange={(v) => {
            setMarket(v);
            setSymbol(undefined);
          }}
        />

        <Card size="small">
          <Row gutter={[16, 16]}>
            <Col xs={24} md={10}>
              <Typography.Text type="secondary">종목 검색</Typography.Text>
              <Select
                showSearch
                allowClear
                style={{ width: "100%", marginTop: 8 }}
                placeholder="종목 선택"
                options={symbolOptions}
                loading={symbolsQuery.isLoading}
                value={symbol}
                onChange={setSymbol}
                filterOption={(input, option) =>
                  (option?.label ?? "").toLowerCase().includes(input.toLowerCase())
                }
              />
            </Col>
            <Col xs={24} md={14}>
              <Space wrap>
                {PERIOD_PRESETS.map((p) => (
                  <Tag.CheckableTag
                    key={p.label}
                    checked={!year && !customRange && periodDays === p.days}
                    onChange={() => {
                      setYear(null);
                      setCustomRange(null);
                      setPeriodDays(p.days);
                    }}
                  >
                    {p.label}
                  </Tag.CheckableTag>
                ))}
                {YEAR_OPTIONS.map((y) => (
                  <Tag.CheckableTag
                    key={y}
                    checked={year === y}
                    onChange={() => {
                      setYear(y);
                      setCustomRange(null);
                    }}
                  >
                    {y}
                  </Tag.CheckableTag>
                ))}
                <DatePicker.RangePicker
                  onChange={(vals) => {
                    if (vals?.[0] && vals[1]) {
                      setCustomRange([vals[0], vals[1]]);
                      setYear(null);
                    } else {
                      setCustomRange(null);
                    }
                  }}
                />
              </Space>
              <div style={{ marginTop: 12 }}>
                <Segmented<TimeframeKey>
                  options={[
                    { label: "일봉", value: "day" },
                    { label: "분봉", value: "minute" },
                  ]}
                  value={timeframe}
                  onChange={setTimeframe}
                />
              </div>
            </Col>
          </Row>
        </Card>

        {symbolInfoQuery.data ? (
          <Card size="small" title="종목 정보">
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }}>
              <Descriptions.Item label="시장">
                {cell((symbolInfoQuery.data as Record<string, unknown>).market)}
              </Descriptions.Item>
              <Descriptions.Item label="종목">
                {cell((symbolInfoQuery.data as Record<string, unknown>).symbol)}
              </Descriptions.Item>
              <Descriptions.Item label="종목명">
                {cell((symbolInfoQuery.data as Record<string, unknown>).name)}
              </Descriptions.Item>
              <Descriptions.Item label="거래상태">
                {(symbolInfoQuery.data as Record<string, unknown>).active
                  ? "ACTIVE"
                  : "INACTIVE"}
              </Descriptions.Item>
              <Descriptions.Item label="일봉 보유">
                {cell((symbolInfoQuery.data as Record<string, unknown>).daily_count)}
              </Descriptions.Item>
              <Descriptions.Item label="분봉 보유">
                {cell((symbolInfoQuery.data as Record<string, unknown>).minute_count)}
              </Descriptions.Item>
              <Descriptions.Item label="최초 일봉">
                {cell((symbolInfoQuery.data as Record<string, unknown>).first_daily)}
              </Descriptions.Item>
              <Descriptions.Item label="최종 일봉">
                {cell((symbolInfoQuery.data as Record<string, unknown>).last_daily)}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        ) : null}

        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: "chart",
              label: "시세 조회",
              children: (
                <Spin spinning={candlesQuery.isFetching}>
                  {!symbol ? (
                    <Empty description="종목을 선택하세요" />
                  ) : candleBody?.policy_message ? (
                    <Alert type="info" showIcon message={candleBody.policy_message} />
                  ) : chartRows.length === 0 ? (
                    <Empty description="선택 기간에 데이터가 없습니다" />
                  ) : (
                    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                      <Row gutter={16}>
                        <Col span={6}>
                          <Statistic title="row count" value={candleBody?.row_count ?? 0} />
                        </Col>
                        <Col span={6}>
                          <Statistic
                            title="최초"
                            value={String(candleBody?.first_date ?? "").slice(0, 10)}
                          />
                        </Col>
                        <Col span={6}>
                          <Statistic
                            title="최종"
                            value={String(candleBody?.last_date ?? "").slice(0, 10)}
                          />
                        </Col>
                      </Row>
                      <Card title="OHLC Candlestick" size="small">
                        <ResponsiveContainer width="100%" height={360}>
                          <ComposedChart data={chartRows}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="dateLabel" minTickGap={24} />
                            <YAxis
                              yAxisId="price"
                              domain={[
                                (dataMin: number) => dataMin * 0.995,
                                (dataMax: number) => dataMax * 1.005,
                              ]}
                            />
                            <Tooltip content={<CandleTooltip />} />
                            <Bar
                              yAxisId="price"
                              dataKey="high"
                              shape={CandlestickBar}
                              isAnimationActive={false}
                              name="Candlestick"
                            />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </Card>
                      <Card title="Volume" size="small">
                        <ResponsiveContainer width="100%" height={160}>
                          <ComposedChart data={chartRows}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="dateLabel" minTickGap={24} />
                            <YAxis />
                            <Tooltip />
                            <Bar dataKey="volume" fill="#722ed1" name="Volume" />
                          </ComposedChart>
                        </ResponsiveContainer>
                      </Card>
                    </Space>
                  )}
                  {candlesQuery.error ? (
                    <Alert
                      type="error"
                      showIcon
                      message={toApiError(candlesQuery.error).message}
                    />
                  ) : null}
                </Spin>
              ),
            },
            {
              key: "collection",
              label: "수집 현황",
              children: (
                <Spin spinning={statusQuery.isLoading}>
                  {statusQuery.data ? (
                    <Space orientation="vertical" style={{ width: "100%" }}>
                      <Alert
                        type="info"
                        showIcon
                        message="Root Cause (확정)"
                        description={
                          <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                            {JSON.stringify(
                              (statusQuery.data as Record<string, unknown>).root_cause,
                              null,
                              2,
                            )}
                          </pre>
                        }
                      />
                      <Card title="수집 Job Heartbeat" size="small">
                        <pre style={{ whiteSpace: "pre-wrap" }}>
                          {JSON.stringify(
                            (statusQuery.data as Record<string, unknown>).collection_jobs,
                            null,
                            2,
                          )}
                        </pre>
                      </Card>
                    </Space>
                  ) : (
                    <Empty />
                  )}
                </Spin>
              ),
            },
            {
              key: "quality",
              label: "데이터 품질",
              children: (
                <Spin spinning={qualityQuery.isLoading}>
                  <Row gutter={[16, 16]}>
                    {qualityItems.map((item) => (
                      <Col xs={24} md={8} key={`${item.exchange_code}-${item.data_kind}`}>
                        <Card
                          title={`${cell(item.exchange_code)} ${cell(item.data_kind)}`}
                          size="small"
                        >
                          <Typography.Title level={4} style={{ marginTop: 0 }}>
                            {cell(item.status_label)}
                          </Typography.Title>
                          <Descriptions column={1} size="small">
                            <Descriptions.Item label="최종">
                              {cell(item.latest_date)}
                            </Descriptions.Item>
                            <Descriptions.Item label="기대">
                              {cell(item.expected_latest_date)}
                            </Descriptions.Item>
                            <Descriptions.Item label="LAG">
                              {cell(item.lag_days)}
                            </Descriptions.Item>
                            <Descriptions.Item label="정책">
                              {cell(item.collection_policy)}
                            </Descriptions.Item>
                          </Descriptions>
                        </Card>
                      </Col>
                    ))}
                  </Row>
                </Spin>
              ),
            },
          ]}
        />
      </Space>
    </AdminPageShell>
  );
}
