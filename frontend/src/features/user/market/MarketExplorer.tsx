"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  Col,
  Input,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export type MarketType = "STOCK" | "CRYPTO";

const STOCK_EXCHANGES = ["KRX", "KOSDAQ"];
const CRYPTO_EXCHANGES = ["UPBIT"];

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function formatNumber(value: unknown, suffix = ""): string {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isFinite(num)) return `${num.toLocaleString("ko-KR")}${suffix}`;
  return `${cell(value)}${suffix}`;
}

interface MarketExplorerProps {
  /** 진입 시 기본 시장 구분 — 주식 화면/암호화폐 화면 공용 컴포넌트 */
  defaultMarketType?: MarketType;
}

/** 시장정보 화면 — 주식·암호화폐 공용 컴포넌트. 종목 검색·현재가·일봉·기술지표 */
export function MarketExplorer({
  defaultMarketType = "STOCK",
}: MarketExplorerProps) {
  const [marketType, setMarketType] = useState<MarketType>(defaultMarketType);
  const [exchangeCode, setExchangeCode] = useState(
    defaultMarketType === "STOCK" ? "KRX" : "UPBIT",
  );
  const [symbol, setSymbol] = useState(
    defaultMarketType === "STOCK" ? "005930" : "KRW-BTC",
  );

  const exchangeOptions = marketType === "STOCK" ? STOCK_EXCHANGES : CRYPTO_EXCHANGES;

  const switchMarketType = (next: MarketType) => {
    setMarketType(next);
    if (next === "STOCK") {
      setExchangeCode("KRX");
      setSymbol("005930");
    } else {
      setExchangeCode("UPBIT");
      setSymbol("KRW-BTC");
    }
  };

  const symbolsQuery = useQuery({
    queryKey: queryKeys.user.marketSymbols(exchangeCode),
    queryFn: () =>
      userApi.listMarketSymbols({ market: exchangeCode, active_only: true }),
    staleTime: 60_000,
  });

  const latestPriceQuery = useQuery({
    queryKey: queryKeys.user.latestPrice(exchangeCode, symbol),
    queryFn: () => userApi.getLatestPrice(exchangeCode, symbol),
    enabled: Boolean(symbol),
    retry: false,
  });

  const quoteQuery = useQuery({
    queryKey: queryKeys.user.realtimeQuote(exchangeCode, symbol),
    queryFn: () => userApi.getRealtimeQuote(exchangeCode, symbol),
    enabled: Boolean(symbol),
    refetchInterval: 5_000,
    retry: false,
  });

  const candlesQuery = useQuery({
    queryKey: ["user", "market", "candles", exchangeCode, symbol],
    queryFn: () => userApi.getDailyCandles(exchangeCode, symbol, { limit: 60 }),
    enabled: Boolean(symbol),
  });

  const indicatorsQuery = useQuery({
    queryKey: ["user", "market", "indicators", exchangeCode, symbol],
    queryFn: () =>
      userApi.getDailyIndicators(exchangeCode, symbol, {
        start_date: daysAgoIso(90),
        end_date: todayIso(),
      }),
    enabled: Boolean(symbol),
  });

  const symbolOptions = useMemo(() => {
    const rows = Array.isArray(symbolsQuery.data)
      ? (symbolsQuery.data as Record<string, unknown>[])
      : extractRows(symbolsQuery.data);
    return rows
      .map((row) => {
        const sym = String(row.symbol ?? "").toUpperCase();
        const name = String(row.name ?? "");
        if (!sym) return null;
        return { value: sym, label: name ? `${sym} · ${name}` : sym };
      })
      .filter((item): item is { value: string; label: string } => Boolean(item));
  }, [symbolsQuery.data]);

  const quote = asRecord(quoteQuery.data);
  const latest = asRecord(latestPriceQuery.data);
  const tradePrice = quote?.trade_price ?? quote?.price ?? latest?.close_price;
  const changeRate = quote?.change_rate ?? latest?.change_rate;
  const usingRealtime = quoteQuery.isSuccess && Boolean(quoteQuery.data);

  const candleRows = extractRows(candlesQuery.data);
  const indicatorRows = extractRows(indicatorsQuery.data);

  return (
    <UserPageShell
      title={marketType === "STOCK" ? "주식 시장정보" : "암호화폐 시장정보"}
      description="주식·업비트 공통 — 종목 검색 · 현재가 · 일봉 · 기술지표"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small">
          <Space wrap size={12}>
            <Radio.Group
              value={marketType}
              onChange={(e) => switchMarketType(e.target.value)}
              optionType="button"
              buttonStyle="solid"
              options={[
                { label: "주식", value: "STOCK" },
                { label: "업비트", value: "CRYPTO" },
              ]}
            />
            <Select
              style={{ width: 130 }}
              value={exchangeCode}
              onChange={(value: string) => setExchangeCode(value)}
              options={exchangeOptions.map((code) => ({
                value: code,
                label: code,
              }))}
            />
            <Select
              style={{ width: 260 }}
              showSearch
              allowClear
              placeholder="종목·마켓 검색"
              loading={symbolsQuery.isLoading}
              value={symbol}
              options={symbolOptions}
              filterOption={(input, option) => {
                const q = input.trim().toUpperCase();
                const label = String(option?.label ?? "").toUpperCase();
                const value = String(option?.value ?? "").toUpperCase();
                return label.includes(q) || value.includes(q);
              }}
              onChange={(value: string | null) => {
                if (value) setSymbol(value);
              }}
            />
            <Input.Search
              placeholder="직접 입력"
              style={{ width: 180 }}
              enterButton="조회"
              allowClear
              onSearch={(value) => {
                const next = value.trim().toUpperCase();
                if (next) setSymbol(next);
              }}
            />
          </Space>
          {symbolsQuery.error ? (
            <Alert
              style={{ marginTop: 12 }}
              type="warning"
              showIcon
              title="종목 목록 조회 실패"
              description={`${toApiError(symbolsQuery.error).message} — 직접 입력으로 조회할 수 있습니다.`}
            />
          ) : null}
        </Card>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={8}>
            <Card
              title="현재가"
              size="small"
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {exchangeCode}:{symbol}
                </Typography.Text>
              }
            >
              <Statistic
                title={usingRealtime ? "현재가 (실시간)" : "현재가 (일봉 종가)"}
                value={formatNumber(tradePrice)}
                loading={quoteQuery.isLoading && latestPriceQuery.isLoading}
              />
              <Typography.Text type="secondary">
                등락률 {formatNumber(changeRate, "%")}
              </Typography.Text>
              {quoteQuery.isError && latestPriceQuery.isError ? (
                <Alert
                  style={{ marginTop: 12 }}
                  type="warning"
                  showIcon
                  title="시세 없음"
                  description="실시간 캐시·일봉 종가가 모두 없습니다. 데이터 수집 상태를 확인하세요."
                />
              ) : null}
            </Card>
          </Col>

          <Col xs={24} lg={16}>
            <Card
              title="일봉"
              size="small"
              loading={candlesQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /user/market/candles/day
                </Typography.Text>
              }
            >
              {candlesQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(candlesQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  pagination={{ pageSize: 8 }}
                  rowKey={(row) => String(row.candle_date ?? row.trade_date)}
                  dataSource={candleRows}
                  locale={{ emptyText: "일봉 데이터 없음" }}
                  columns={[
                    { title: "날짜", dataIndex: "candle_date", render: cell },
                    {
                      title: "시가",
                      dataIndex: "open_price",
                      render: (v) => formatNumber(v),
                    },
                    {
                      title: "고가",
                      dataIndex: "high_price",
                      render: (v) => formatNumber(v),
                    },
                    {
                      title: "저가",
                      dataIndex: "low_price",
                      render: (v) => formatNumber(v),
                    },
                    {
                      title: "종가",
                      dataIndex: "close_price",
                      render: (v) => formatNumber(v),
                    },
                    {
                      title: "거래량",
                      dataIndex: "volume",
                      render: (v) => formatNumber(v),
                    },
                  ]}
                />
              )}
            </Card>
          </Col>
        </Row>

        <Card
          title="기술지표 (최근 90일)"
          size="small"
          loading={indicatorsQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /user/market/indicators/daily
            </Typography.Text>
          }
        >
          {indicatorsQuery.error ? (
            <Alert
              type="error"
              showIcon
              title={toApiError(indicatorsQuery.error).message}
            />
          ) : (
            <Table
              size="small"
              pagination={{ pageSize: 8 }}
              rowKey={(row) => String(row.trade_date)}
              dataSource={indicatorRows.slice(-30).reverse()}
              locale={{ emptyText: "지표 데이터 없음" }}
              columns={[
                { title: "날짜", dataIndex: "trade_date", render: cell },
                { title: "MA5", dataIndex: "ma5", render: (v) => formatNumber(v) },
                { title: "MA20", dataIndex: "ma20", render: (v) => formatNumber(v) },
                { title: "RSI14", dataIndex: "rsi14", render: (v) => formatNumber(v) },
                { title: "MACD", dataIndex: "macd", render: (v) => formatNumber(v) },
                {
                  title: "상태",
                  dataIndex: "status_code",
                  render: cell,
                },
              ]}
            />
          )}
        </Card>
      </Space>
    </UserPageShell>
  );
}
