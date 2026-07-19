"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Form,
  Input,
  InputNumber,
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
import { useEffect, useMemo, useState } from "react";

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { userRoutes } from "@/config/routes";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { useMyPaperAccountId } from "@/features/user/hooks/useMyPaperAccountId";
import * as userApi from "@/features/user/api/userApi";
import { filterOpenOrders } from "@/features/user/trading/openOrders";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

const DEFAULT_EXCHANGE = "KRX";

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

type OrderFormValues = {
  exchange_code: string;
  symbol: string;
  order_type: "LIMIT" | "MARKET";
  quantity: number;
  price?: number;
  account_id: number;
};

export default function UserTradingPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { accountId } = useMyPaperAccountId();
  const [mode, setMode] = useState<"PAPER" | "LIVE">("PAPER");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [watch, setWatch] = useState({
    exchange_code: DEFAULT_EXCHANGE,
    symbol: "005930",
  });
  const [form] = Form.useForm<OrderFormValues>();

  // 내 Paper 계좌 ID가 로드되면 주문 폼에 반영
  useEffect(() => {
    if (accountId != null) {
      form.setFieldValue("account_id", accountId);
    }
  }, [accountId, form]);

  const symbolsQuery = useQuery({
    queryKey: queryKeys.user.marketSymbols(watch.exchange_code),
    queryFn: () =>
      userApi.listMarketSymbols({
        market: watch.exchange_code,
        active_only: true,
      }),
    staleTime: 60_000,
  });

  const killSwitch = useQuery({
    queryKey: queryKeys.user.killSwitch(),
    queryFn: userApi.getKillSwitch,
    refetchInterval: 15_000,
  });

  const quoteQuery = useQuery({
    queryKey: queryKeys.user.realtimeQuote(
      watch.exchange_code,
      watch.symbol,
    ),
    queryFn: () =>
      userApi.getRealtimeQuote(watch.exchange_code, watch.symbol),
    refetchInterval: 2_000,
    retry: false,
  });

  const latestPriceQuery = useQuery({
    queryKey: queryKeys.user.latestPrice(
      watch.exchange_code,
      watch.symbol,
    ),
    queryFn: () =>
      userApi.getLatestPrice(watch.exchange_code, watch.symbol),
    refetchInterval: 10_000,
    retry: false,
    // 실시간 캐시 없을 때 일봉 종가 폴백
    enabled: quoteQuery.isError || !quoteQuery.data,
  });

  const paperOrdersQuery = useQuery({
    queryKey: [...queryKeys.user.paperOrders(), "trading"],
    queryFn: () => userApi.listPaperOrders(),
    refetchInterval: 5_000,
  });

  const tradingOrdersQuery = useQuery({
    queryKey: [...queryKeys.user.orders(), "trading", { limit: 30, account_id: accountId }],
    queryFn: () =>
      userApi.listOrders({
        account_id: accountId as number,
        limit: 30,
        offset: 0,
      }),
    enabled: accountId != null,
    refetchInterval: 5_000,
  });

  const executionsQuery = useQuery({
    queryKey: [...queryKeys.user.executions(), "trading", { limit: 30 }],
    queryFn: () => userApi.listExecutions({ limit: 30 }),
    refetchInterval: 5_000,
  });

  const invalidateTrading = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.user.paperOrders() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.user.orders() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.user.executions() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.user.killSwitch() }),
    ]);
  };

  const submitPaper = useMutation({
    mutationFn: userApi.createPaperOrder,
    onSuccess: async () => {
      message.success("Paper 주문 접수");
      await invalidateTrading();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const submitLive = useMutation({
    mutationFn: userApi.submitLiveOrder,
    onSuccess: async (data) => {
      const row = asRecord(data);
      if (row?.allowed === false) {
        message.warning(`주문 거부: ${cell(row.reason_code ?? "BLOCKED")}`);
      } else {
        message.success("Live 주문 제출 (Risk·Kill Switch 통과)");
      }
      await invalidateTrading();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const cancelPaper = useMutation({
    mutationFn: userApi.cancelPaperOrder,
    onSuccess: async () => {
      message.success("Paper 주문 취소");
      await invalidateTrading();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const cancelLive = useMutation({
    mutationFn: (orderId: number) => userApi.cancelTradingOrder(orderId),
    onSuccess: async () => {
      message.success("주문 취소 요청");
      await invalidateTrading();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const kill = asRecord(killSwitch.data);
  const killActive =
    kill?.active === true ||
    String(kill?.status ?? "").toUpperCase() === "ACTIVE";

  const quote = asRecord(quoteQuery.data);
  const latest = asRecord(latestPriceQuery.data);
  const tradePrice =
    quote?.trade_price ??
    quote?.price ??
    latest?.close_price ??
    latest?.close;
  const changeRate = quote?.change_rate ?? latest?.change_rate;
  const usingRealtime = quoteQuery.isSuccess && Boolean(quoteQuery.data);
  const usingLatestFallback =
    !usingRealtime && latestPriceQuery.isSuccess && Boolean(latestPriceQuery.data);

  const symbolOptions = useMemo(() => {
    const rows = Array.isArray(symbolsQuery.data)
      ? (symbolsQuery.data as Record<string, unknown>[])
      : extractRows(symbolsQuery.data);
    return rows
      .map((row) => {
        const symbol = String(row.symbol ?? "").toUpperCase();
        const name = String(row.name ?? "");
        if (!symbol) return null;
        return {
          value: symbol,
          label: name ? `${symbol} · ${name}` : symbol,
          name,
        };
      })
      .filter((item): item is { value: string; label: string; name: string } =>
        Boolean(item),
      );
  }, [symbolsQuery.data]);

  const paperRows = extractRows(paperOrdersQuery.data);
  const orderRows = extractRows(tradingOrdersQuery.data);
  const executionRows = extractRows(executionsQuery.data);

  const openPaperOrders = useMemo(
    () => filterOpenOrders(paperRows),
    [paperRows],
  );
  const openTradingOrders = useMemo(
    () => filterOpenOrders(orderRows),
    [orderRows],
  );

  const selectSymbol = (symbol: string, exchange = watch.exchange_code) => {
    const next = {
      exchange_code: exchange.trim().toUpperCase(),
      symbol: symbol.trim().toUpperCase(),
    };
    setWatch(next);
    form.setFieldsValue({
      exchange_code: next.exchange_code,
      symbol: next.symbol,
    });
  };

  const onSubmitOrder = async (values: OrderFormValues) => {
    const payload = {
      exchange_code: values.exchange_code.trim().toUpperCase(),
      symbol: values.symbol.trim().toUpperCase(),
      side,
      order_type: values.order_type,
      quantity: values.quantity,
      price: values.price,
      account_id: values.account_id,
    };

    // Paper Risk 검사용 — 시장가여도 참조 가격 필요
    if (
      (payload.price == null || payload.price <= 0) &&
      Number.isFinite(Number(tradePrice)) &&
      Number(tradePrice) > 0
    ) {
      payload.price = Number(tradePrice);
    }

    selectSymbol(payload.symbol, payload.exchange_code);

    if (mode === "PAPER") {
      if (accountId == null) {
        message.error("Paper 계좌를 불러오는 중입니다. 잠시 후 다시 시도하세요.");
        return;
      }
      if (payload.price == null || payload.price <= 0) {
        message.error("가격이 필요합니다. 시세를 조회하거나 가격을 입력하세요.");
        return;
      }
      await submitPaper.mutateAsync({
        ...payload,
        account_id: accountId,
        order_type: values.order_type,
        price: payload.price,
      });
      return;
    }

    await submitLive.mutateAsync({
      account_id: values.account_id,
      exchange_code: payload.exchange_code,
      symbol: payload.symbol,
      side,
      order_type: values.order_type,
      quantity: values.quantity,
      price: payload.price,
    });
  };

  const submitting = submitPaper.isPending || submitLive.isPending;

  return (
    <UserPageShell
      title="매매"
      description="종목검색 · 현재가 · 매수/매도 · 취소 · 미체결 · 체결 · STEP44"
      extra={
        <Space wrap>
          <Button size="small">
            <Link href={userRoutes.portfolio}>포트폴리오</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.dashboard}>Dashboard</Link>
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap size={8}>
          <Tag color={killActive ? "error" : "success"}>
            Kill Switch: {killActive ? "ACTIVE" : "INACTIVE"}
          </Tag>
          <Tag>Mode: {mode}</Tag>
          <Tag>Account: #{accountId ?? "…"}</Tag>
          <Tag>
            시세:{" "}
            {usingRealtime
              ? "realtime"
              : usingLatestFallback
                ? "latest-fallback"
                : "없음"}
          </Tag>
          <Tag>
            {watch.exchange_code}:{watch.symbol}
          </Tag>
        </Space>

        {killActive ? (
          <Alert
            type="error"
            showIcon
            title="Kill Switch ACTIVE"
            description="신규 주문이 차단될 수 있습니다. 관리자 해제 후 다시 시도하세요."
          />
        ) : null}

        {mode === "LIVE" ? (
          <Alert
            type="warning"
            showIcon
            title="LIVE 모드"
            description="실제 주문 경로(/order-execution/submit)입니다. Risk·Kill Switch가 강제 적용됩니다."
          />
        ) : null}

        <Row gutter={[16, 16]}>
          {/* 종목 검색 + 현재가 */}
          <Col xs={24} lg={8}>
            <Card
              title="종목 검색 · 현재가"
              size="small"
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /market/symbols · /realtime-quotes · /prices/latest
                </Typography.Text>
              }
            >
              <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    거래소
                  </Typography.Text>
                  <Select
                    style={{ width: "100%", marginTop: 4 }}
                    value={watch.exchange_code}
                    options={[
                      { value: "KRX", label: "KRX" },
                      { value: "KOSDAQ", label: "KOSDAQ" },
                      { value: "UPBIT", label: "UPBIT" },
                    ]}
                    onChange={(value: string) => {
                      setWatch((prev) => ({
                        ...prev,
                        exchange_code: value,
                      }));
                      form.setFieldValue("exchange_code", value);
                    }}
                  />
                </div>
                <div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    종목 검색
                  </Typography.Text>
                  <Select
                    style={{ width: "100%", marginTop: 4 }}
                    showSearch
                    allowClear
                    placeholder="코드 또는 종목명"
                    loading={symbolsQuery.isLoading}
                    value={watch.symbol}
                    options={symbolOptions}
                    filterOption={(input, option) => {
                      const q = input.trim().toUpperCase();
                      const label = String(option?.label ?? "").toUpperCase();
                      const value = String(option?.value ?? "").toUpperCase();
                      return label.includes(q) || value.includes(q);
                    }}
                    notFoundContent={
                      symbolsQuery.error
                        ? toApiError(symbolsQuery.error).message
                        : "종목 없음"
                    }
                    onChange={(value: string | null) => {
                      if (value) selectSymbol(value);
                    }}
                  />
                </div>
                <Input.Search
                  placeholder="직접 입력 (예: 005930)"
                  enterButton="조회"
                  allowClear
                  onSearch={(value) => {
                    const symbol = value.trim().toUpperCase();
                    if (!symbol) return;
                    selectSymbol(symbol);
                  }}
                />

                {symbolsQuery.error ? (
                  <Alert
                    type="warning"
                    showIcon
                    title="종목 목록 조회 실패"
                    description={`${toApiError(symbolsQuery.error).message} — 직접 입력으로 조회할 수 있습니다.`}
                  />
                ) : null}

                <Statistic
                  title={
                    usingRealtime
                      ? "현재가 (실시간)"
                      : usingLatestFallback
                        ? "현재가 (종가 폴백)"
                        : "현재가"
                  }
                  value={formatNumber(tradePrice)}
                  loading={quoteQuery.isLoading && latestPriceQuery.isLoading}
                />
                <Typography.Text type="secondary">
                  등락률 {formatPct(changeRate)}
                </Typography.Text>
                {quoteQuery.isError && latestPriceQuery.isError ? (
                  <Alert
                    type="warning"
                    showIcon
                    title="시세 없음"
                    description="실시간 캐시·일봉 종가가 모두 없습니다. 심볼을 확인하거나 시세 수집을 확인하세요."
                  />
                ) : null}
                {quoteQuery.isError && latestPriceQuery.isSuccess ? (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    실시간 캐시 없음(404) → 일봉 종가 사용
                  </Typography.Text>
                ) : null}
              </Space>
            </Card>
          </Col>

          {/* 매수 / 매도 */}
          <Col xs={24} lg={16}>
            <Card
              title="매수 · 매도"
              size="small"
              extra={
                <Radio.Group
                  size="small"
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  optionType="button"
                  buttonStyle="solid"
                  options={[
                    { label: "Paper", value: "PAPER" },
                    { label: "Live", value: "LIVE" },
                  ]}
                />
              }
            >
              <Space style={{ marginBottom: 12 }}>
                <Button
                  type={side === "BUY" ? "primary" : "default"}
                  onClick={() => setSide("BUY")}
                >
                  매수
                </Button>
                <Button
                  danger={side === "SELL"}
                  type={side === "SELL" ? "primary" : "default"}
                  onClick={() => setSide("SELL")}
                >
                  매도
                </Button>
              </Space>

              <Form
                form={form}
                layout="inline"
                onFinish={(values) => void onSubmitOrder(values)}
                initialValues={{
                  exchange_code: DEFAULT_EXCHANGE,
                  symbol: "005930",
                  order_type: "LIMIT",
                  quantity: 1,
                  price: undefined,
                  account_id: accountId ?? undefined,
                }}
              >
                <Form.Item
                  name="account_id"
                  label="계좌"
                  rules={[{ required: true }]}
                >
                  <InputNumber min={1} />
                </Form.Item>
                <Form.Item
                  name="exchange_code"
                  label="거래소"
                  rules={[{ required: true }]}
                >
                  <Input style={{ width: 90 }} />
                </Form.Item>
                <Form.Item
                  name="symbol"
                  label="종목"
                  rules={[{ required: true }]}
                >
                  <Input style={{ width: 110 }} />
                </Form.Item>
                <Form.Item
                  name="order_type"
                  label="유형"
                  rules={[{ required: true }]}
                >
                  <Select
                    style={{ width: 110 }}
                    options={[
                      { value: "LIMIT", label: "지정가" },
                      { value: "MARKET", label: "시장가" },
                    ]}
                  />
                </Form.Item>
                <Form.Item
                  name="quantity"
                  label="수량"
                  rules={[{ required: true, message: "수량" }]}
                >
                  <InputNumber min={0.0001} />
                </Form.Item>
                <Form.Item
                  name="price"
                  label="가격"
                  rules={[
                    ({ getFieldValue }) => ({
                      validator(_, value) {
                        if (getFieldValue("order_type") === "MARKET") {
                          return Promise.resolve();
                        }
                        if (value == null || Number(value) <= 0) {
                          return Promise.reject(
                            new Error("지정가는 가격이 필요합니다"),
                          );
                        }
                        return Promise.resolve();
                      },
                    }),
                  ]}
                >
                  <InputNumber min={0.01} />
                </Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={submitting}
                  danger={side === "SELL"}
                  disabled={killActive}
                >
                  {side === "BUY" ? "매수 주문" : "매도 주문"}
                </Button>
                <Button
                  type="link"
                  onClick={() => {
                    const price = Number(tradePrice);
                    if (Number.isFinite(price) && price > 0) {
                      form.setFieldValue("price", price);
                      form.setFieldValue("symbol", watch.symbol);
                      form.setFieldValue(
                        "exchange_code",
                        watch.exchange_code,
                      );
                    }
                  }}
                >
                  시세 반영
                </Button>
              </Form>
              <Typography.Paragraph
                type="secondary"
                style={{ marginTop: 12, marginBottom: 0 }}
              >
                Paper: POST /paper-orders · Live: POST /order-execution/submit
              </Typography.Paragraph>
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          {/* 미체결 + 주문 취소 */}
          <Col xs={24} lg={12}>
            <Card
              title="미체결 조회 · 주문 취소"
              size="small"
              loading={
                paperOrdersQuery.isLoading || tradingOrdersQuery.isLoading
              }
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /paper-orders · /orders
                </Typography.Text>
              }
            >
              <Table
                size="small"
                pagination={false}
                rowKey={(row) =>
                  tableRowKey(row, [
                    "paper_order_id",
                    "order_id",
                    "symbol",
                  ])
                }
                dataSource={
                  [
                    ...openPaperOrders.map((row) => ({
                      ...row,
                      _channel: "PAPER",
                    })),
                    ...openTradingOrders.map((row) => ({
                      ...row,
                      _channel: "LIVE",
                    })),
                  ].slice(0, 20) as Record<string, unknown>[]
                }
                locale={{ emptyText: "미체결 주문 없음" }}
                columns={[
                  {
                    title: "채널",
                    dataIndex: "_channel",
                    width: 70,
                    render: (v: unknown) => <Tag>{cell(v)}</Tag>,
                  },
                  {
                    title: "ID",
                    render: (_: unknown, row: Record<string, unknown>) =>
                      cell(row.paper_order_id ?? row.order_id),
                    width: 70,
                  },
                  { title: "심볼", dataIndex: "symbol", render: cell },
                  {
                    title: "측",
                    dataIndex: "side",
                    width: 60,
                    render: cell,
                  },
                  {
                    title: "상태",
                    dataIndex: "status_code",
                    render: (v: unknown, row: Record<string, unknown>) => (
                      <Tag>{cell(v ?? row.status)}</Tag>
                    ),
                  },
                  {
                    title: "취소",
                    width: 90,
                    render: (_: unknown, row: Record<string, unknown>) => {
                      const id = Number(row.paper_order_id ?? row.order_id);
                      if (!Number.isFinite(id)) return null;
                      const isPaper = row._channel === "PAPER";
                      return (
                        <Button
                          size="small"
                          danger
                          loading={
                            isPaper
                              ? cancelPaper.isPending
                              : cancelLive.isPending
                          }
                          onClick={() => {
                            if (isPaper) {
                              cancelPaper.mutate(id);
                            } else {
                              cancelLive.mutate(id);
                            }
                          }}
                        >
                          취소
                        </Button>
                      );
                    },
                  },
                ]}
              />
            </Card>
          </Col>

          {/* 체결 조회 */}
          <Col xs={24} lg={12}>
            <Card
              title="체결 조회"
              size="small"
              loading={executionsQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /executions
                </Typography.Text>
              }
            >
              {executionsQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(executionsQuery.error).message}
                />
              ) : (
                <Table
                  size="small"
                  pagination={{ pageSize: 8 }}
                  rowKey={(row) =>
                    tableRowKey(row, [
                      "execution_id",
                      "trading_execution_id",
                      "order_id",
                      "symbol",
                    ])
                  }
                  dataSource={executionRows.slice(0, 50)}
                  locale={{ emptyText: "체결 없음" }}
                  columns={[
                    {
                      title: "주문",
                      dataIndex: "order_id",
                      width: 70,
                      render: cell,
                    },
                    { title: "심볼", dataIndex: "symbol", render: cell },
                    {
                      title: "수량",
                      dataIndex: "quantity",
                      render: (v, row) =>
                        formatNumber(v ?? row.execution_quantity),
                    },
                    {
                      title: "가격",
                      dataIndex: "price",
                      render: (v) => formatNumber(v),
                    },
                    {
                      title: "시각",
                      dataIndex: "executed_at",
                      render: (v, row) => cell(v ?? row.created_at),
                    },
                  ]}
                />
              )}
            </Card>
          </Col>
        </Row>

        <Card
          title="최근 Paper 주문"
          size="small"
          loading={paperOrdersQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /paper-orders
            </Typography.Text>
          }
        >
          <Table
            size="small"
            pagination={{ pageSize: 8 }}
            rowKey={(row) =>
              tableRowKey(row, ["paper_order_id", "symbol", "created_at"])
            }
            dataSource={paperRows.slice(0, 50)}
            locale={{ emptyText: "Paper 주문 없음" }}
            columns={[
              {
                title: "ID",
                dataIndex: "paper_order_id",
                width: 70,
                render: cell,
              },
              { title: "심볼", dataIndex: "symbol", render: cell },
              { title: "측", dataIndex: "side", width: 60, render: cell },
              {
                title: "수량",
                dataIndex: "requested_quantity",
                render: (v, row) => formatNumber(v ?? row.quantity),
              },
              {
                title: "가격",
                dataIndex: "price",
                render: (v) => formatNumber(v),
              },
              {
                title: "상태",
                dataIndex: "status_code",
                render: (v, row) => <Tag>{cell(v ?? row.status)}</Tag>,
              },
            ]}
          />
        </Card>

        {/* 실시간 SSE UI — 엔드포인트는 있으나 User 화면 미연결 */}
        <Card title="실시간 시세 스트림" size="small">
          {/* TODO: GET /api/v1/realtime-quotes/stream/sse — User SSE/WS 구독 UI */}
          <UnimplementedNotice
            feature="실시간 시세 SSE/WS UI"
            reason="Backend에 GET /realtime-quotes/{ex}/{symbol} 및 /stream/sse 가 있습니다. 현재 화면은 폴링으로 현재가만 조회합니다. SSE 구독 UI는 후속 STEP에서 연결합니다."
            relatedApis={[
              "GET /api/v1/realtime-quotes/{exchange}/{symbol}",
              "GET /api/v1/realtime-quotes/stream/sse",
              "GET /api/v1/prices/latest/{exchange}/{symbol}",
            ]}
          />
        </Card>
      </Space>
    </UserPageShell>
  );
}
