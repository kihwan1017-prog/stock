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
  Select,
  Space,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type OrderRow = Record<string, unknown>;

export default function AdminOrdersPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<{
    account_id?: number;
    symbol?: string;
    limit: number;
    offset: number;
  }>({ limit: 50, offset: 0 });
  const [detailId, setDetailId] = useState<number | null>(null);

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
                exchange_code: v.exchange_code,
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
              account_id: 1,
              exchange_code: "KRX",
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
            <Form.Item name="exchange_code" label="exchange" rules={[{ required: true }]}>
              <Input style={{ width: 90 }} />
            </Form.Item>
            <Form.Item name="symbol" label="symbol" rules={[{ required: true }]}>
              <Input placeholder="005930" style={{ width: 100 }} />
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
              limit: v.limit ?? 50,
              offset: v.offset ?? 0,
            })
          }
        >
          <Form.Item name="account_id" label="account_id">
            <InputNumber min={1} />
          </Form.Item>
          <Form.Item name="symbol" label="symbol">
            <Input allowClear placeholder="005930" style={{ width: 120 }} />
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
            { title: "order_id", dataIndex: "order_id", sorter: true },
            { title: "symbol", dataIndex: "symbol", sorter: true },
            { title: "side", dataIndex: "side_code" },
            { title: "status", dataIndex: "status_code" },
            { title: "qty", dataIndex: "order_quantity" },
            { title: "price", dataIndex: "order_price" },
            {
              title: "취소",
              render: (_, row) => (
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
              account_id: 1,
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
    </AdminPageShell>
  );
}
