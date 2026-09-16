"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Collapse,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { resolveOrderTradingKind } from "@/features/admin/autotrading/orderOwnership";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { OrderFillDetailDrawer } from "@/features/admin/orders/OrderFillDetailDrawer";
import { OrderFillMonitoringDashboard } from "@/features/admin/orders/OrderFillMonitoringDashboard";
import {
  canShowResolveNotSubmittedButton,
  outboxStatusForOrder,
} from "@/features/admin/orders/resolveNotSubmittedGate";
import {
  ORDER_LIST_TAB_LABELS,
  orderMatchesTab,
  type OrderListTab,
} from "@/features/admin/orders/orderListTabs";
import { canShowUnsubmittedRetireButton } from "@/features/admin/orders/unsubmittedRetireGate";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import {
  ADMIN_ORDER_READ_PREFIX,
  ADMIN_ORDER_READ_SUFFIX,
  ADMIN_ORDER_READ_TITLES,
  buildOrderReadColumns,
} from "@/shared/orders/orderReadColumns";

type OrderRow = Record<string, unknown>;

const DEFAULT_PAPER_ACCOUNT_ID = Number(
  process.env.NEXT_PUBLIC_DEFAULT_PAPER_ACCOUNT_ID ?? "1",
);

const RESOLVE_WARNING =
  "브로커 미전송 여부를 서버에서 재검증합니다. 확인되지 않으면 폐기할 수 없습니다.";

function readInitialOrderListTab(): OrderListTab {
  if (typeof window === "undefined") return "all";
  try {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t === "open" || t === "fills" || t === "rejected" || t === "all") {
      return t;
    }
  } catch {
    /* ignore */
  }
  return "all";
}

export default function AdminOrdersPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [listTab, setListTab] = useState<OrderListTab>(readInitialOrderListTab);
  const [ownershipFilter, setOwnershipFilter] = useState<
    "ALL" | "AUTO" | "MANUAL" | "UNKNOWN"
  >("ALL");
  const [filters, setFilters] = useState<{
    account_id?: number;
    symbol?: string;
    exchange_code?: string;
    broker_code?: string;
    limit: number;
    offset: number;
  }>({ limit: 50, offset: 0 });

  const [detailId, setDetailId] = useState<number | null>(null);
  const [retireRow, setRetireRow] = useState<OrderRow | null>(null);
  const [retireReason, setRetireReason] = useState("");
  const [retirePreview, setRetirePreview] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [resolveRow, setResolveRow] = useState<OrderRow | null>(null);
  const [resolveReason, setResolveReason] = useState("");
  const [resolvePreview, setResolvePreview] = useState<Record<
    string,
    unknown
  > | null>(null);

  const killSwitch = useQuery({
    queryKey: queryKeys.admin.killSwitch(),
    queryFn: adminApi.getKillSwitch,
  });
  const list = useQuery({
    queryKey: queryKeys.admin.orders(filters),
    queryFn: () => adminApi.listOrders(filters),
  });
  const outbox = useQuery({
    queryKey: queryKeys.admin.orderOutbox(),
    queryFn: adminApi.getOrderOutbox,
  });
  const paperOrders = useQuery({
    queryKey: queryKeys.admin.paperOrders(),
    queryFn: () => adminApi.listPaperOrders({ limit: 50 }),
  });

  const invalidateOrders = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.orders({}) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.orderOutbox() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.paperOrders() });
    void queryClient.invalidateQueries({
      queryKey: ["admin", "autotrading-performance"],
    });
  };

  const submit = useMutation({
    mutationFn: adminApi.submitOrder,
    onSuccess: (data) => {
      const row = data as { allowed?: boolean; reason_code?: string };
      if (row.allowed === false) {
        message.warning(`주문 거부: ${row.reason_code ?? "BLOCKED"}`);
      } else {
        message.success("주문 등록(Risk·Kill Switch 통과)");
      }
      invalidateOrders();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const cancelTrading = useMutation({
    mutationFn: (orderId: number) => adminApi.cancelTradingOrder(orderId),
    onSuccess: () => {
      message.success("주문 취소 요청 완료");
      invalidateOrders();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const openRetireModal = async (row: OrderRow) => {
    const orderId = Number(row.order_id ?? row.id);
    if (!Number.isFinite(orderId)) return;
    try {
      const preview = (await adminApi.previewRetireUnsubmittedOrder(
        orderId,
      )) as Record<string, unknown>;
      setRetirePreview(preview);
      if (preview.retirable !== true) {
        message.error(
          `폐기 불가: ${Array.isArray(preview.blockers) ? preview.blockers.join(", ") : "blocked"}`,
        );
        return;
      }
      setRetireRow(row);
      setRetireReason("");
    } catch (err) {
      message.error(toApiError(err).message);
    }
  };

  const retireUnsubmitted = useMutation({
    mutationFn: ({ orderId, reason }: { orderId: number; reason: string }) =>
      adminApi.retireUnsubmittedOrder(orderId, reason),
    onSuccess: () => {
      message.success("미전송 주문을 내부 폐기했습니다 (Upbit 미호출)");
      setRetireRow(null);
      setRetirePreview(null);
      setRetireReason("");
      invalidateOrders();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const openResolveModal = async (row: OrderRow) => {
    const orderId = Number(row.order_id ?? row.id);
    if (!Number.isFinite(orderId)) return;
    try {
      const preview = (await adminApi.previewResolveNotSubmittedOrder(
        orderId,
      )) as Record<string, unknown>;
      setResolvePreview(preview);
      if (preview.resolvable !== true) {
        message.error(
          `미전송 확인 불가: ${Array.isArray(preview.blockers) ? preview.blockers.join(", ") : "blocked"}`,
        );
        return;
      }
      setResolveRow(row);
      setResolveReason("");
    } catch (err) {
      message.error(toApiError(err).message);
    }
  };

  const resolveNotSubmitted = useMutation({
    mutationFn: ({ orderId, reason }: { orderId: number; reason: string }) =>
      adminApi.resolveNotSubmittedOrder(orderId, reason),
    onSuccess: () => {
      message.success(
        "미전송 확인(CONFIRMED_NOT_SUBMITTED) 후 내부 폐기 완료",
      );
      setResolveRow(null);
      setResolvePreview(null);
      setResolveReason("");
      invalidateOrders();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const createPaper = useMutation({
    mutationFn: adminApi.createPaperOrder,
    onSuccess: () => {
      message.success("Paper 주문 등록 완료");
      invalidateOrders();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const cancelPaper = useMutation({
    mutationFn: (orderId: number) => adminApi.cancelPaperOrder(orderId),
    onSuccess: () => {
      message.success("Paper 주문 취소 완료");
      invalidateOrders();
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const rows = useMemo(() => extractRows(list.data) as OrderRow[], [list.data]);
  const filteredRows = useMemo(() => {
    return rows.filter((row) => {
      if (
        !orderMatchesTab(
          String(row.status_code ?? ""),
          row.filled_quantity,
          listTab,
        )
      ) {
        return false;
      }
      const hint = resolveOrderTradingKind(row);
      if (ownershipFilter === "ALL") return true;
      return hint.kind === ownershipFilter;
    });
  }, [rows, listTab, ownershipFilter]);
  const outboxRows = useMemo(
    () => extractRows(outbox.data) as OrderRow[],
    [outbox.data],
  );
  const paperRows = useMemo(
    () => extractRows(paperOrders.data) as OrderRow[],
    [paperOrders.data],
  );

  const killActive = Boolean(
    String(
      (killSwitch.data as { status?: string } | undefined)?.status ?? "",
    ).toUpperCase() === "ACTIVE",
  );

  return (
    <AdminPageShell
      title="주문·체결"
      description="오늘 자동매매 주문·체결의 기준 화면입니다. 대시보드·업비트/키움에는 요약만 두고 상세는 여기서 확인합니다. 수동 REAL 주문은 아래 운영 도구에 분리되어 있습니다."
      extra={
        <Space wrap>
          <Tag color={killActive ? "error" : "success"}>
            긴급 중지 {killActive ? "켜짐" : "꺼짐"}
          </Tag>
          <Typography.Text type="secondary">
            실거래는 LIVE Gate + 명시 승인 시에만
          </Typography.Text>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <OrderFillMonitoringDashboard onOpenDetail={setDetailId} />

        <Collapse
          items={[
            {
              key: "ops",
              label: "운영 도구 / 고급 (수동 주문 · Paper)",
              children: (
                <Space orientation="vertical" size={16} style={{ width: "100%" }}>
                  <Alert
                    type="warning"
                    showIcon
                    title="수동 주문은 자동매매 외 운영 작업입니다."
                    description="실계좌 수동주문은 기존 LIVE Gate · Risk · Kill Switch를 그대로 적용합니다. 실수 방지를 위해 기본 운영 화면과 분리되어 있습니다."
                  />

                  <Card title="수동 주문" size="small">
                    <Typography.Paragraph type="secondary">
                      기술 경로: 주문 실행 제출 API (관리자 전용)
                    </Typography.Paragraph>
                    <Form
                      layout="inline"
                      onFinish={(v) =>
                        submit.mutate({
                          account_id: v.account_id,
                          broker_code: v.broker_code,
                          exchange_code: v.exchange_code,
                          environment: v.environment,
                          symbol: v.symbol,
                          side: v.side,
                          order_type: v.order_type,
                          quantity: v.quantity,
                          price: v.price,
                          account_number: v.account_number || undefined,
                          strategy_code: v.strategy_code || undefined,
                        })
                      }
                      initialValues={{
                        account_id: DEFAULT_PAPER_ACCOUNT_ID,
                        broker_code: "KIWOOM",
                        exchange_code: "KRX",
                        environment: "PAPER",
                        side: "BUY",
                        order_type: "LIMIT",
                        quantity: 1,
                      }}
                    >
                      <Form.Item
                        name="account_id"
                        label="account_id"
                        rules={[{ required: true }]}
                      >
                        <InputNumber min={1} />
                      </Form.Item>
                      <Form.Item name="account_number" label="account_number">
                        <Input placeholder="Risk 계좌번호" style={{ width: 140 }} />
                      </Form.Item>
                      <Form.Item
                        name="broker_code"
                        label="broker"
                        rules={[{ required: true }]}
                      >
                        <Select
                          options={[
                            { value: "KIWOOM", label: "KIWOOM" },
                            { value: "UPBIT", label: "UPBIT" },
                          ]}
                          style={{ width: 110 }}
                        />
                      </Form.Item>
                      <Form.Item
                        name="exchange_code"
                        label="exchange"
                        rules={[{ required: true }]}
                      >
                        <Select
                          options={[
                            { value: "KRX", label: "KRX" },
                            { value: "UPBIT", label: "UPBIT" },
                          ]}
                          style={{ width: 110 }}
                        />
                      </Form.Item>
                      <Form.Item name="environment" label="env">
                        <Select
                          options={[
                            { value: "PAPER", label: "PAPER" },
                            { value: "LIVE", label: "LIVE" },
                          ]}
                          style={{ width: 100 }}
                        />
                      </Form.Item>
                      <Form.Item
                        name="symbol"
                        label="symbol"
                        rules={[{ required: true }]}
                      >
                        <Input
                          placeholder="005930 / KRW-BTC"
                          style={{ width: 120 }}
                        />
                      </Form.Item>
                      <Form.Item name="side" label="side" rules={[{ required: true }]}>
                        <Select
                          options={[
                            { value: "BUY", label: "BUY" },
                            { value: "SELL", label: "SELL" },
                          ]}
                          style={{ width: 90 }}
                        />
                      </Form.Item>
                      <Form.Item name="order_type" label="type">
                        <Select
                          options={[
                            { value: "LIMIT", label: "LIMIT" },
                            { value: "MARKET", label: "MARKET" },
                          ]}
                          style={{ width: 110 }}
                        />
                      </Form.Item>
                      <Form.Item
                        name="quantity"
                        label="qty"
                        rules={[{ required: true }]}
                      >
                        <InputNumber min={0.0001} />
                      </Form.Item>
                      <Form.Item name="price" label="price" rules={[{ required: true }]}>
                        <InputNumber min={0.01} />
                      </Form.Item>
                      <Form.Item name="strategy_code" label="strategy">
                        <Input allowClear style={{ width: 120 }} />
                      </Form.Item>
                      <PermissionButton
                        permission="trading:write"
                        type="primary"
                        htmlType="submit"
                        loading={submit.isPending}
                      >
                        수동 주문
                      </PermissionButton>
                    </Form>
                  </Card>

                  <Collapse
                    items={[
                      {
                        key: "paper",
                        label: "Paper 주문 테스트",
                        children: (
                          <Space
                            orientation="vertical"
                            size={12}
                            style={{ width: "100%" }}
                          >
                            <Typography.Paragraph type="secondary">
                              기술 경로: Paper 주문 API · Risk+Kill Switch
                            </Typography.Paragraph>
                            <Form
                              layout="inline"
                              onFinish={(v) =>
                                createPaper.mutate({
                                  exchange_code: v.exchange_code,
                                  symbol: v.symbol,
                                  side: v.side,
                                  order_type: v.order_type,
                                  quantity: v.quantity,
                                  price: v.price,
                                  account_id: v.account_id,
                                  account_number: v.account_number || undefined,
                                })
                              }
                              initialValues={{
                                account_id: DEFAULT_PAPER_ACCOUNT_ID,
                                exchange_code: "KRX",
                                side: "BUY",
                                order_type: "LIMIT",
                                quantity: 1,
                                price: 70000,
                              }}
                            >
                              <Form.Item name="account_id" label="paper account_id">
                                <InputNumber min={1} />
                              </Form.Item>
                              <Form.Item name="account_number" label="account_number">
                                <Input allowClear style={{ width: 140 }} />
                              </Form.Item>
                              <Form.Item
                                name="exchange_code"
                                label="exchange"
                                rules={[{ required: true }]}
                              >
                                <Input style={{ width: 90 }} />
                              </Form.Item>
                              <Form.Item
                                name="symbol"
                                label="symbol"
                                rules={[{ required: true }]}
                              >
                                <Input style={{ width: 100 }} />
                              </Form.Item>
                              <Form.Item
                                name="side"
                                label="side"
                                rules={[{ required: true }]}
                              >
                                <Select
                                  options={[
                                    { value: "BUY", label: "BUY" },
                                    { value: "SELL", label: "SELL" },
                                  ]}
                                  style={{ width: 90 }}
                                />
                              </Form.Item>
                              <Form.Item name="order_type" label="type">
                                <Select
                                  options={[
                                    { value: "LIMIT", label: "LIMIT" },
                                    { value: "MARKET", label: "MARKET" },
                                  ]}
                                  style={{ width: 110 }}
                                />
                              </Form.Item>
                              <Form.Item
                                name="quantity"
                                label="qty"
                                rules={[{ required: true }]}
                              >
                                <InputNumber min={0.0001} />
                              </Form.Item>
                              <Form.Item
                                name="price"
                                label="price"
                                rules={[{ required: true }]}
                              >
                                <InputNumber min={0.01} />
                              </Form.Item>
                              <PermissionButton
                                permission="trading:write"
                                type="primary"
                                htmlType="submit"
                                loading={createPaper.isPending}
                              >
                                Paper 주문
                              </PermissionButton>
                            </Form>
                            <AdminDataTable
                              title="모의거래 주문"
                              loading={paperOrders.isLoading}
                              error={
                                paperOrders.error
                                  ? toApiError(paperOrders.error)
                                  : null
                              }
                              rowKey={(r) =>
                                cell(r.order_id ?? JSON.stringify(r))
                              }
                              columns={[
                                { title: "주문번호", dataIndex: "order_id" },
                                { title: "종목", dataIndex: "symbol" },
                                { title: "매수/매도", dataIndex: "side" },
                                { title: "상태", dataIndex: "status_code" },
                                {
                                  title: "수량",
                                  dataIndex: "requested_quantity",
                                },
                                {
                                  title: "취소",
                                  render: (_, row) => (
                                    <PermissionButton
                                      permission="trading:write"
                                      size="small"
                                      danger
                                      loading={cancelPaper.isPending}
                                      onClick={() =>
                                        cancelPaper.mutate(Number(row.order_id))
                                      }
                                    >
                                      취소
                                    </PermissionButton>
                                  ),
                                },
                              ]}
                              dataSource={paperRows}
                            />
                          </Space>
                        ),
                      },
                      {
                        key: "legacy-list",
                        label: "전체 주문 검색 · 미전송 폐기",
                        children: (
                          <Space
                            orientation="vertical"
                            size={12}
                            style={{ width: "100%" }}
                          >
                            <Tabs
                              activeKey={listTab}
                              onChange={(k) => setListTab(k as OrderListTab)}
                              items={(
                                Object.keys(ORDER_LIST_TAB_LABELS) as OrderListTab[]
                              ).map((key) => ({
                                key,
                                label: ORDER_LIST_TAB_LABELS[key],
                              }))}
                            />
                            <Form
                              layout="inline"
                              initialValues={filters}
                              onFinish={(v) =>
                                setFilters({
                                  account_id: v.account_id,
                                  symbol: v.symbol || undefined,
                                  exchange_code: v.exchange_code || undefined,
                                  broker_code: v.broker_code || undefined,
                                  limit: v.limit ?? 50,
                                  offset: v.offset ?? 0,
                                })
                              }
                            >
                              <Form.Item name="account_id" label="account_id">
                                <InputNumber min={1} />
                              </Form.Item>
                              <Form.Item name="broker_code" label="broker">
                                <Select
                                  allowClear
                                  options={[
                                    { value: "KIWOOM", label: "KIWOOM" },
                                    { value: "UPBIT", label: "UPBIT" },
                                  ]}
                                  style={{ width: 110 }}
                                />
                              </Form.Item>
                              <Form.Item name="exchange_code" label="exchange">
                                <Select
                                  allowClear
                                  options={[
                                    { value: "KRX", label: "KRX" },
                                    { value: "UPBIT", label: "UPBIT" },
                                  ]}
                                  style={{ width: 110 }}
                                />
                              </Form.Item>
                              <Form.Item name="symbol" label="symbol">
                                <Input
                                  allowClear
                                  placeholder="005930 / KRW-BTC"
                                  style={{ width: 140 }}
                                />
                              </Form.Item>
                              <Form.Item label="AUTO/MANUAL">
                                <Select
                                  value={ownershipFilter}
                                  onChange={(v) => setOwnershipFilter(v)}
                                  options={[
                                    { value: "ALL", label: "전체" },
                                    { value: "AUTO", label: "자동매매" },
                                    { value: "MANUAL", label: "일반매매" },
                                    { value: "UNKNOWN", label: "확인 필요" },
                                  ]}
                                  style={{ width: 120 }}
                                />
                              </Form.Item>
                              <Form.Item name="limit" label="limit">
                                <InputNumber min={1} max={500} />
                              </Form.Item>
                              <Form.Item name="offset" label="offset">
                                <InputNumber min={0} />
                              </Form.Item>
                              <Button type="primary" htmlType="submit">
                                검색
                              </Button>
                            </Form>

                            <AdminDataTable
                              title={`주문 목록 (${ORDER_LIST_TAB_LABELS[listTab]})`}
                              loading={list.isLoading}
                              error={list.error ? toApiError(list.error) : null}
                              rowKey={(r) =>
                                cell(r.order_id ?? r.id ?? JSON.stringify(r))
                              }
                              columns={[
                                ...buildOrderReadColumns(ADMIN_ORDER_READ_PREFIX, {
                                  titles: ADMIN_ORDER_READ_TITLES,
                                  sorters: { order_id: true },
                                }),
                                { title: "거래소/증권사", dataIndex: "broker_code" },
                                {
                                  title: "자동/수동",
                                  key: "ownership",
                                  width: 110,
                                  render: (_: unknown, row: OrderRow) => {
                                    const hint = resolveOrderTradingKind(row);
                                    return (
                                      <Tag
                                        color={
                                          hint.kind === "AUTO"
                                            ? "processing"
                                            : hint.kind === "MANUAL"
                                              ? "default"
                                              : "warning"
                                        }
                                        title={hint.reason}
                                      >
                                        {hint.labelKo}
                                        {hint.confidence === "low" ? "*" : ""}
                                      </Tag>
                                    );
                                  },
                                },
                                ...buildOrderReadColumns(ADMIN_ORDER_READ_SUFFIX, {
                                  titles: ADMIN_ORDER_READ_TITLES,
                                  sorters: { symbol: true },
                                }),
                                {
                                  title: "체결수량",
                                  dataIndex: "filled_quantity",
                                  render: (v: unknown) => cell(v),
                                },
                                {
                                  title: "전략",
                                  dataIndex: "strategy_code",
                                  render: (v: unknown) => cell(v),
                                },
                                {
                                  title: "거래소 UUID",
                                  dataIndex: "broker_order_id",
                                  render: (v: unknown) => cell(v),
                                },
                                {
                                  title: "주문시각",
                                  dataIndex: "created_at",
                                  render: (v: unknown) => cell(v),
                                },
                                {
                                  title: "취소",
                                  render: (_, row) => (
                                    <Space size={4} wrap>
                                      <PermissionButton
                                        permission="trading:write"
                                        size="small"
                                        danger
                                        loading={cancelTrading.isPending}
                                        onClick={() =>
                                          cancelTrading.mutate(
                                            Number(row.order_id ?? row.id),
                                          )
                                        }
                                      >
                                        취소
                                      </PermissionButton>
                                      {(() => {
                                        const oid = Number(row.order_id ?? row.id);
                                        const ox = Number.isFinite(oid)
                                          ? outboxStatusForOrder(oid, outboxRows)
                                          : null;
                                        const showResolve =
                                          canShowResolveNotSubmittedButton(row, ox);
                                        const showRetire =
                                          !showResolve &&
                                          canShowUnsubmittedRetireButton(row);
                                        return (
                                          <>
                                            {showResolve ? (
                                              <PermissionButton
                                                permission="trading:write"
                                                size="small"
                                                danger
                                                onClick={() =>
                                                  void openResolveModal(row)
                                                }
                                              >
                                                미전송 확인 후 폐기
                                              </PermissionButton>
                                            ) : null}
                                            {showRetire ? (
                                              <PermissionButton
                                                permission="trading:write"
                                                size="small"
                                                onClick={() =>
                                                  void openRetireModal(row)
                                                }
                                              >
                                                미전송 주문 폐기
                                              </PermissionButton>
                                            ) : null}
                                          </>
                                        );
                                      })()}
                                    </Space>
                                  ),
                                },
                                {
                                  title: "상세",
                                  render: (_, row) => (
                                    <Button
                                      size="small"
                                      onClick={() =>
                                        setDetailId(Number(row.order_id ?? row.id))
                                      }
                                    >
                                      보기
                                    </Button>
                                  ),
                                },
                              ]}
                              dataSource={filteredRows}
                              pagination={{
                                pageSize: filters.limit,
                                current:
                                  Math.floor(filters.offset / filters.limit) + 1,
                                onChange: (page, pageSize) =>
                                  setFilters((prev) => ({
                                    ...prev,
                                    limit: pageSize,
                                    offset: (page - 1) * pageSize,
                                  })),
                              }}
                            />

                            <AdminJsonCard
                              title="주문 대기열(Outbox)"
                              loading={outbox.isLoading}
                              error={
                                outbox.error ? toApiError(outbox.error) : null
                              }
                              data={outbox.data}
                            />
                          </Space>
                        ),
                      },
                    ]}
                  />
                </Space>
              ),
            },
          ]}
        />
      </Space>

      <OrderFillDetailDrawer
        orderId={detailId}
        onClose={() => setDetailId(null)}
      />

      <Modal
        title="미전송 LIVE 주문을 내부 폐기하시겠습니까?"
        open={retireRow != null}
        onCancel={() => {
          setRetireRow(null);
          setRetirePreview(null);
          setRetireReason("");
        }}
        okText="내부 폐기"
        okButtonProps={{
          danger: true,
          disabled: retireReason.trim().length < 1,
          loading: retireUnsubmitted.isPending,
        }}
        onOk={() => {
          const orderId = Number(retireRow?.order_id ?? retireRow?.id);
          if (!Number.isFinite(orderId) || retireReason.trim().length < 1) {
            return;
          }
          retireUnsubmitted.mutate({
            orderId,
            reason: retireReason.trim(),
          });
        }}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary">
          Upbit API를 호출하지 않습니다. 내부 주문/outbox만 정리합니다.
        </Typography.Paragraph>
        {retirePreview ? (
          <AdminJsonCard title="미리보기" data={retirePreview} />
        ) : null}
        <Input.TextArea
          rows={3}
          value={retireReason}
          onChange={(e) => setRetireReason(e.target.value)}
          placeholder="폐기 사유 (필수)"
        />
      </Modal>

      <Modal
        title="미전송 확인 후 폐기"
        open={resolveRow != null}
        onCancel={() => {
          setResolveRow(null);
          setResolvePreview(null);
          setResolveReason("");
        }}
        okText="확인 후 폐기"
        okButtonProps={{
          danger: true,
          disabled: resolveReason.trim().length < 1,
          loading: resolveNotSubmitted.isPending,
        }}
        onOk={() => {
          const orderId = Number(resolveRow?.order_id ?? resolveRow?.id);
          if (!Number.isFinite(orderId) || resolveReason.trim().length < 1) {
            return;
          }
          resolveNotSubmitted.mutate({
            orderId,
            reason: resolveReason.trim(),
          });
        }}
        destroyOnHidden
      >
        <Alert type="warning" showIcon title={RESOLVE_WARNING} />
        {resolvePreview ? (
          <AdminJsonCard title="미리보기" data={resolvePreview} />
        ) : null}
        <Input.TextArea
          rows={3}
          value={resolveReason}
          onChange={(e) => setResolveReason(e.target.value)}
          placeholder="사유 (필수)"
        />
      </Modal>
    </AdminPageShell>
  );
}
