"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  DatePicker,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Typography,
} from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { useEffect, useMemo, useState } from "react";

import { PageContainer } from "@/components/common/PageContainer";
import type { TradeExecution, TradeOrder, UserAccount } from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const { RangePicker } = DatePicker;

function inDateRange(
  value: string | undefined,
  range: [Dayjs, Dayjs] | null,
): boolean {
  if (!range || !value) return true;
  const ts = dayjs(value);
  if (!ts.isValid()) return true;
  return (
    (ts.isAfter(range[0].startOf("day")) || ts.isSame(range[0].startOf("day"))) &&
    (ts.isBefore(range[1].endOf("day")) || ts.isSame(range[1].endOf("day")))
  );
}

export default function UserTradesPage() {
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(
    null,
  );
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [symbolFilter, setSymbolFilter] = useState("");
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [ordersPage, setOrdersPage] = useState(1);
  const [executionsPage, setExecutionsPage] = useState(1);
  const pageSize = 10;

  const accountsQuery = useQuery({
    queryKey: queryKeys.user.userAccounts(),
    queryFn: () => userApi.listUserAccounts(),
  });

  const paperAccounts = useMemo(
    () =>
      (accountsQuery.data?.items ?? []).filter(
        (row: UserAccount) => row.account_type === "PAPER" && row.is_active,
      ),
    [accountsQuery.data],
  );

  const defaultPaper = useMemo(
    () => paperAccounts.find((row) => row.is_default) ?? paperAccounts[0] ?? null,
    [paperAccounts],
  );

  useEffect(() => {
    if (selectedAccountId !== null) return;
    if (defaultPaper) {
      setSelectedAccountId(defaultPaper.account_id);
    }
  }, [defaultPaper, selectedAccountId]);

  const accountReady =
    selectedAccountId !== null && selectedAccountId > 0;

  const orderParams = {
    account_id: selectedAccountId ?? undefined,
    status_code: statusFilter,
    symbol: symbolFilter.trim() || undefined,
    limit: 200,
  };

  const ordersQuery = useQuery({
    queryKey: queryKeys.user.orders(orderParams),
    queryFn: () =>
      userApi.listOrders({
        account_id: selectedAccountId!,
        status_code: statusFilter,
        symbol: symbolFilter.trim() || undefined,
        limit: 200,
      }),
    enabled: accountReady,
  });

  const executionsQuery = useQuery({
    queryKey: queryKeys.user.executions({
      account_id: selectedAccountId,
      limit: 200,
    }),
    queryFn: () =>
      userApi.listExecutions({
        account_id: selectedAccountId!,
        limit: 200,
      }),
    enabled: accountReady,
  });

  const filteredOrders = useMemo(() => {
    const rows = ordersQuery.data ?? [];
    return rows.filter((row: TradeOrder) =>
      inDateRange(row.created_at, dateRange),
    );
  }, [ordersQuery.data, dateRange]);

  const filteredExecutions = useMemo(() => {
    const rows = executionsQuery.data ?? [];
    return rows.filter((row: TradeExecution) => {
      if (symbolFilter.trim()) {
        const symbol = String(row.symbol ?? "").toUpperCase();
        if (!symbol.includes(symbolFilter.trim().toUpperCase())) {
          return false;
        }
      }
      return inDateRange(row.executed_at, dateRange);
    });
  }, [executionsQuery.data, dateRange, symbolFilter]);

  const noAccounts =
    !accountsQuery.isLoading && paperAccounts.length === 0;

  return (
    <PageContainer
      title="거래내역"
      description="선택한 계좌의 주문·체결 내역입니다. account_id 결정 후에만 API를 호출합니다."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {accountsQuery.error ? (
          <Alert
            type="error"
            showIcon
            title={toApiError(accountsQuery.error).message}
          />
        ) : null}

        {noAccounts ? (
          <Empty
            description={
              <span>
                연결된 계좌가 없습니다.
                <br />
                <Typography.Link href="/user/account">
                  내 계좌에서 계좌를 먼저 연결해 주세요.
                </Typography.Link>
              </span>
            }
          />
        ) : (
          <>
            <Card size="small" title="필터">
              <Space wrap>
                <Select
                  style={{ width: 280 }}
                  loading={accountsQuery.isLoading}
                  placeholder="계좌 선택"
                  value={selectedAccountId ?? undefined}
                  options={paperAccounts.map((row) => ({
                    value: row.account_id,
                    label: `${row.account_name}${row.is_default ? " (기본)" : ""}`,
                  }))}
                  onChange={(value: number) => {
                    setSelectedAccountId(value);
                    setOrdersPage(1);
                    setExecutionsPage(1);
                  }}
                />
                <Select
                  allowClear
                  style={{ width: 160 }}
                  placeholder="주문 상태"
                  value={statusFilter}
                  onChange={(value?: string) => {
                    setStatusFilter(value);
                    setOrdersPage(1);
                  }}
                  options={[
                    { value: "CREATED", label: "CREATED" },
                    { value: "ACCEPTED", label: "ACCEPTED" },
                    { value: "PARTIALLY_FILLED", label: "PARTIALLY_FILLED" },
                    { value: "FILLED", label: "FILLED" },
                    { value: "CANCELLED", label: "CANCELLED" },
                    { value: "REJECTED", label: "REJECTED" },
                  ]}
                />
                <Input
                  style={{ width: 140 }}
                  placeholder="종목"
                  value={symbolFilter}
                  onChange={(event) => {
                    setSymbolFilter(event.target.value);
                    setOrdersPage(1);
                    setExecutionsPage(1);
                  }}
                  allowClear
                />
                <RangePicker
                  value={dateRange}
                  onChange={(values) => {
                    setDateRange(
                      values && values[0] && values[1]
                        ? [values[0], values[1]]
                        : null,
                    );
                    setOrdersPage(1);
                    setExecutionsPage(1);
                  }}
                />
              </Space>
            </Card>

            {!accountReady ? (
              <Alert
                type="info"
                showIcon
                title="계좌를 선택하면 거래내역을 불러옵니다."
              />
            ) : null}

            <Card title="주문 내역" size="small">
              {ordersQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(ordersQuery.error).message}
                  style={{ marginBottom: 12 }}
                />
              ) : null}
              <Table<TradeOrder>
                size="small"
                loading={ordersQuery.isLoading || accountsQuery.isLoading}
                rowKey={(row) => String(row.order_id ?? JSON.stringify(row))}
                dataSource={filteredOrders}
                locale={{ emptyText: "주문 내역이 없습니다." }}
                pagination={{
                  current: ordersPage,
                  pageSize,
                  total: filteredOrders.length,
                  onChange: setOrdersPage,
                  showSizeChanger: false,
                }}
                columns={[
                  { title: "ID", dataIndex: "order_id", width: 80 },
                  { title: "종목", dataIndex: "symbol", width: 100 },
                  { title: "시장", dataIndex: "exchange_code", width: 80 },
                  { title: "구분", dataIndex: "side_code", width: 80 },
                  { title: "상태", dataIndex: "status_code", width: 120 },
                  { title: "수량", dataIndex: "order_quantity", width: 90 },
                  { title: "가격", dataIndex: "order_price", width: 90 },
                  {
                    title: "시각",
                    dataIndex: "created_at",
                    render: (value?: string) =>
                      value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-",
                  },
                ]}
              />
            </Card>

            <Card title="체결 내역" size="small">
              {executionsQuery.error ? (
                <Alert
                  type="error"
                  showIcon
                  title={toApiError(executionsQuery.error).message}
                  style={{ marginBottom: 12 }}
                />
              ) : null}
              <Table<TradeExecution>
                size="small"
                loading={executionsQuery.isLoading || accountsQuery.isLoading}
                rowKey={(row) =>
                  String(row.execution_id ?? JSON.stringify(row))
                }
                dataSource={filteredExecutions}
                locale={{ emptyText: "체결 내역이 없습니다." }}
                pagination={{
                  current: executionsPage,
                  pageSize,
                  total: filteredExecutions.length,
                  onChange: setExecutionsPage,
                  showSizeChanger: false,
                }}
                columns={[
                  { title: "ID", dataIndex: "execution_id", width: 80 },
                  { title: "주문", dataIndex: "order_id", width: 80 },
                  { title: "종목", dataIndex: "symbol", width: 100 },
                  { title: "구분", dataIndex: "side_code", width: 80 },
                  {
                    title: "체결가",
                    dataIndex: "execution_price",
                    width: 100,
                  },
                  {
                    title: "수량",
                    dataIndex: "execution_quantity",
                    width: 90,
                  },
                  {
                    title: "시각",
                    dataIndex: "executed_at",
                    render: (value?: string) =>
                      value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-",
                  },
                ]}
              />
            </Card>
          </>
        )}
      </Space>
    </PageContainer>
  );
}
