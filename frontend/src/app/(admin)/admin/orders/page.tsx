"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Card,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import {
  canShowResolveNotSubmittedButton,
  outboxStatusForOrder,
} from "@/features/admin/orders/resolveNotSubmittedGate";
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

export default function AdminOrdersPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
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
  const detail = useQuery({
    queryKey: queryKeys.admin.orderDetail(detailId ?? 0),
    queryFn: () => adminApi.getOrder(detailId!),
    enabled: detailId !== null,
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
      title="주문관리"
      description="order-execution/submit(Risk+Kill Switch) · 취소 · Paper Trading"
      extra={
        <Space wrap>
          <Tag color={killActive ? "error" : "success"}>
            Kill Switch {killActive ? "ACTIVE" : "OFF"}
          </Tag>
          <Typography.Text type="secondary">
            실거래는 KIWOOM_LIVE_ORDER_ENABLED + transition 승인 시에만
          </Typography.Text>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card title="주문 등록 (POST /order-execution/submit)" size="small">
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
            <Form.Item name="account_id" label="account_id" rules={[{ required: true }]}>
              <InputNumber min={1} />
            </Form.Item>
            <Form.Item name="account_number" label="account_number">
              <Input placeholder="Risk 계좌번호" style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="broker_code" label="broker" rules={[{ required: true }]}>
              <Select
                options={[
                  { value: "KIWOOM", label: "KIWOOM" },
                  { value: "UPBIT", label: "UPBIT" },
                ]}
                style={{ width: 110 }}
              />
            </Form.Item>
            <Form.Item name="exchange_code" label="exchange" rules={[{ required: true }]}>
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
            <Form.Item name="symbol" label="symbol" rules={[{ required: true }]}>
              <Input placeholder="005930 / KRW-BTC" style={{ width: 120 }} />
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
            <Form.Item name="quantity" label="qty" rules={[{ required: true }]}>
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
              주문 등록
            </PermissionButton>
          </Form>
        </Card>

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
            <Input allowClear placeholder="005930 / KRW-BTC" style={{ width: 140 }} />
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
          title="GET /orders"
          loading={list.isLoading}
          error={list.error ? toApiError(list.error) : null}
          rowKey={(r) => cell(r.order_id ?? r.id ?? JSON.stringify(r))}
          columns={[
            // M6-B: COMMON_READ + Admin-only broker + actions (순서 유지)
            ...buildOrderReadColumns(ADMIN_ORDER_READ_PREFIX, {
              titles: ADMIN_ORDER_READ_TITLES,
              sorters: { order_id: true },
            }),
            { title: "broker", dataIndex: "broker_code" },
            ...buildOrderReadColumns(ADMIN_ORDER_READ_SUFFIX, {
              titles: ADMIN_ORDER_READ_TITLES,
              sorters: { symbol: true },
            }),
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
                      cancelTrading.mutate(Number(row.order_id ?? row.id))
                    }
                  >
                    취소
                  </PermissionButton>
                  {(() => {
                    const oid = Number(row.order_id ?? row.id);
                    const ox = Number.isFinite(oid)
                      ? outboxStatusForOrder(oid, outboxRows)
                      : null;
                    const showResolve = canShowResolveNotSubmittedButton(
                      row,
                      ox,
                    );
                    const showRetire =
                      !showResolve && canShowUnsubmittedRetireButton(row);
                    return (
                      <>
                        {showResolve ? (
                          <PermissionButton
                            permission="trading:write"
                            size="small"
                            danger
                            onClick={() => void openResolveModal(row)}
                          >
                            미전송 확인 후 폐기
                          </PermissionButton>
                        ) : null}
                        {showRetire ? (
                          <PermissionButton
                            permission="trading:write"
                            size="small"
                            onClick={() => void openRetireModal(row)}
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
                  onClick={() => setDetailId(Number(row.order_id ?? row.id))}
                >
                  보기
                </Button>
              ),
            },
          ]}
          dataSource={rows}
          pagination={{
            pageSize: filters.limit,
            current: Math.floor(filters.offset / filters.limit) + 1,
            onChange: (page, pageSize) =>
              setFilters((prev) => ({
                ...prev,
                limit: pageSize,
                offset: (page - 1) * pageSize,
              })),
          }}
        />

        <Divider />

        <Card title="Paper Trading (POST /paper-orders · Risk+Kill Switch)" size="small">
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
            <Form.Item name="exchange_code" label="exchange" rules={[{ required: true }]}>
              <Input style={{ width: 90 }} />
            </Form.Item>
            <Form.Item name="symbol" label="symbol" rules={[{ required: true }]}>
              <Input style={{ width: 100 }} />
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
            <Form.Item name="quantity" label="qty" rules={[{ required: true }]}>
              <InputNumber min={0.0001} />
            </Form.Item>
            <Form.Item name="price" label="price" rules={[{ required: true }]}>
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
        </Card>

        <AdminDataTable
          title="GET /paper-orders"
          loading={paperOrders.isLoading}
          error={paperOrders.error ? toApiError(paperOrders.error) : null}
          rowKey={(r) => cell(r.order_id ?? JSON.stringify(r))}
          columns={[
            { title: "order_id", dataIndex: "order_id" },
            { title: "symbol", dataIndex: "symbol" },
            { title: "side", dataIndex: "side" },
            { title: "status", dataIndex: "status_code" },
            { title: "qty", dataIndex: "requested_quantity" },
            {
              title: "취소",
              render: (_, row) => (
                <PermissionButton
                  permission="trading:write"
                  size="small"
                  danger
                  loading={cancelPaper.isPending}
                  onClick={() => cancelPaper.mutate(Number(row.order_id))}
                >
                  취소
                </PermissionButton>
              ),
            },
          ]}
          dataSource={paperRows}
        />

        <AdminJsonCard
          title="GET /order-outbox"
          loading={outbox.isLoading}
          error={outbox.error ? toApiError(outbox.error) : null}
          data={outbox.data}
        />
      </Space>

      <Drawer
        title={`주문 상세 #${detailId}`}
        open={detailId !== null}
        onClose={() => setDetailId(null)}
        size={480}
      >
        <AdminJsonCard
          title="GET /orders/{id}"
          loading={detail.isLoading}
          error={detail.error ? toApiError(detail.error) : null}
          data={detail.data}
        />
      </Drawer>

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
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          <Typography.Text>
            Order ID: {cell(retirePreview?.order_id ?? retireRow?.order_id)}
          </Typography.Text>
          <Typography.Text>
            UBA: {cell(retirePreview?.user_broker_account_id)}
          </Typography.Text>
          <Typography.Text>
            종목: {cell(retirePreview?.symbol ?? retireRow?.symbol)}
          </Typography.Text>
          <Typography.Text>
            방향: {cell(retirePreview?.side ?? retireRow?.side_code)}
          </Typography.Text>
          <Typography.Text>
            주문금액:{" "}
            {cell(
              retirePreview?.estimated_amount ??
                (retireRow?.order_quantity != null &&
                retireRow?.order_price != null
                  ? Number(retireRow.order_quantity) *
                    Number(retireRow.order_price)
                  : null),
            )}
          </Typography.Text>
          <Typography.Text type="secondary">
            broker UUID 없음 · submission attempt 0
          </Typography.Text>
          <Typography.Text type="warning">
            업비트에는 취소 요청을 보내지 않습니다.
          </Typography.Text>
          <Input.TextArea
            rows={3}
            value={retireReason}
            onChange={(e) => setRetireReason(e.target.value)}
            placeholder="폐기 사유 (필수)"
            maxLength={2000}
          />
        </Space>
      </Modal>

      <Modal
        title="미전송 확인 후 폐기 (CONFIRMED_NOT_SUBMITTED)"
        open={resolveRow != null}
        onCancel={() => {
          setResolveRow(null);
          setResolvePreview(null);
          setResolveReason("");
        }}
        okText="미전송 확인 후 폐기"
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
        <Space orientation="vertical" size="small" style={{ width: "100%" }}>
          <Typography.Text type="warning">{RESOLVE_WARNING}</Typography.Text>
          <Typography.Text>
            Order ID: {cell(resolvePreview?.order_id ?? resolveRow?.order_id)}
          </Typography.Text>
          <Typography.Text>
            Outbox: {cell(resolvePreview?.outbox_id)} (
            {cell(resolvePreview?.outbox_status)})
          </Typography.Text>
          <Typography.Text>
            UBA: {cell(resolvePreview?.user_broker_account_id)}
          </Typography.Text>
          <Typography.Text>
            identifier: {cell(resolvePreview?.identifier)}
          </Typography.Text>
          <Typography.Text type="secondary">
            로컬 실패 증거: {cell(resolvePreview?.local_failure_evidence)}
          </Typography.Text>
          <Typography.Text type="secondary">
            일반 미전송 폐기는 계속 BLOCK · POST /v1/orders 없음
          </Typography.Text>
          <Input.TextArea
            rows={3}
            value={resolveReason}
            onChange={(e) => setResolveReason(e.target.value)}
            placeholder="확인·폐기 사유 (필수)"
            maxLength={2000}
          />
        </Space>
      </Modal>
    </AdminPageShell>
  );
}
