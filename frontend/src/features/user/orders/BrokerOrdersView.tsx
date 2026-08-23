"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Empty, Select, Space, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { useEffect, useMemo, useState } from "react";

import { userRoutes } from "@/config/routes";
import type { TradeOrder, UserAccount } from "@/features/user/api/userApi";
import * as userApi from "@/features/user/api/userApi";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import {
  USER_ORDER_READ_COLUMN_ORDER,
  USER_ORDER_READ_TITLES,
  buildOrderReadColumns,
  replaceOrderReadColumn,
} from "@/shared/orders/orderReadColumns";

export type BrokerCode = "KIWOOM" | "UPBIT" | "PAPER";

interface BrokerOrdersViewProps {
  title: string;
  brokerCode: BrokerCode;
}

/**
 * 브로커별 주문·체결 화면.
 * KIWOOM/UPBIT: UserBrokerAccount 단위 조회.
 * PAPER: Paper account_id 단위 조회.
 */
export function BrokerOrdersView({ title, brokerCode }: BrokerOrdersViewProps) {
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(
    null,
  );
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const usesBrokerAccount = brokerCode === "KIWOOM" || brokerCode === "UPBIT";

  const accountsQuery = useQuery({
    queryKey: queryKeys.user.userAccounts(),
    queryFn: () => userApi.listUserAccounts(),
  });

  const selectableAccounts = useMemo(() => {
    const items = accountsQuery.data?.items ?? [];
    if (usesBrokerAccount) {
      return items.filter(
        (row: UserAccount) =>
          row.account_type === brokerCode && row.is_active,
      );
    }
    return items.filter(
      (row: UserAccount) => row.account_type === "PAPER" && row.is_active,
    );
  }, [accountsQuery.data, brokerCode, usesBrokerAccount]);

  const defaultAccount = useMemo(
    () =>
      selectableAccounts.find((row) => row.is_default) ??
      selectableAccounts[0] ??
      null,
    [selectableAccounts],
  );

  useEffect(() => {
    if (selectedAccountId !== null) return;
    if (defaultAccount) {
      // 초기 기본 계좌 선택 — 사용자 변경 전 1회
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 기본값 동기화
      setSelectedAccountId(defaultAccount.account_id);
    }
  }, [defaultAccount, selectedAccountId]);

  const accountReady = selectedAccountId !== null && selectedAccountId > 0;
  const noAccounts =
    !accountsQuery.isLoading && selectableAccounts.length === 0;

  const ordersQuery = useQuery({
    queryKey: queryKeys.user.orders({
      account_id: usesBrokerAccount ? undefined : selectedAccountId,
      user_broker_account_id: usesBrokerAccount
        ? selectedAccountId
        : undefined,
      broker_code: brokerCode,
      limit: 200,
    }),
    queryFn: () =>
      userApi.listOrders(
        usesBrokerAccount
          ? {
              user_broker_account_id: selectedAccountId!,
              broker_code: brokerCode,
              limit: 200,
            }
          : {
              account_id: selectedAccountId!,
              broker_code: brokerCode,
              limit: 200,
            },
      ),
    enabled: accountReady,
  });

  const rows = ordersQuery.data ?? [];

  // M6-B: COMMON_READ + User rich status override + created_at
  const orderColumns = useMemo(() => {
    const common = buildOrderReadColumns<TradeOrder>(USER_ORDER_READ_COLUMN_ORDER, {
      titles: USER_ORDER_READ_TITLES,
      widths: {
        order_id: 80,
        symbol: 100,
        exchange_code: 80,
        side_code: 80,
        status_code: 220,
        order_quantity: 90,
        order_price: 90,
      },
    });
    const withRichStatus = replaceOrderReadColumn<TradeOrder>(common, "status_code", {
      title: "상태",
      dataIndex: "status_code",
      key: "status_code",
      width: 220,
      render: (value: unknown, record: TradeOrder) => {
        const code = String(value ?? "");
        const labelMap: Record<string, string> = {
          SUBMITTING: "주문 전송 중",
          AMBIGUOUS_SUBMISSION: "주문 확인 중",
          REMOTE_LOOKUP_PENDING: "재확인 예정",
          ACCEPTED: "거래소 주문 확인 완료",
          SENT: "거래소 주문 확인 완료",
          MANUAL_REVIEW_REQUIRED: "관리자 확인 필요",
          IDENTITY_CONFLICT: "관리자 확인 필요",
          FILLED: "체결 완료",
          CANCELED: "취소",
          CANCELLED: "취소",
          REJECTED: "거부",
          PARTIALLY_FILLED: "부분 체결",
        };
        const label = labelMap[code] ?? (code ? `확인 필요 (${code})` : "—");
        // STEP 8-5-14 — 재확인 진행 상황 안내 (Claim/Lock 비노출)
        const isAmbiguousLike =
          code === "AMBIGUOUS_SUBMISSION" ||
          code === "REMOTE_LOOKUP_PENDING";
        if (
          !record ||
          (!isAmbiguousLike && code !== "MANUAL_REVIEW_REQUIRED")
        ) {
          return label;
        }
        const attemptCount = Number(record.remote_lookup_attempt_count ?? 0);
        if (code === "MANUAL_REVIEW_REQUIRED") {
          return (
            <span>
              {label}
              <br />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                자동 재조회 {attemptCount}회 완료 — 관리자가 확인 후
                처리합니다.
              </Typography.Text>
            </span>
          );
        }
        const nextLookupAt = record.next_remote_lookup_at
          ? dayjs(String(record.next_remote_lookup_at)).format("HH:mm:ss")
          : null;
        return (
          <span>
            {label}
            <br />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {nextLookupAt
                ? `다음 재조회 ${nextLookupAt} (시도 ${attemptCount}회)`
                : `자동 재조회 대기 중 (시도 ${attemptCount}회)`}
            </Typography.Text>
          </span>
        );
      },
    });
    const createdAt: ColumnsType<TradeOrder>[number] = {
      title: "시각",
      dataIndex: "created_at",
      render: (value?: string) =>
        value ? dayjs(value).format("YYYY-MM-DD HH:mm") : "-",
    };
    return [...withRichStatus, createdAt];
  }, []);

  return (
    <UserPageShell
      title={title}
      description={
        usesBrokerAccount
          ? `${brokerCode} 연결 계좌(UserBrokerAccount) 단위 주문·체결 내역입니다.`
          : "Paper 계좌 단위 주문·체결 내역입니다."
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="계좌 단위 격리"
          description={
            usesBrokerAccount
              ? "실계좌 주문은 user_broker_account_id 기준으로 조회·격리됩니다."
              : "Paper 주문은 account_id 기준으로 조회됩니다."
          }
        />

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
                {usesBrokerAccount
                  ? `연결된 ${brokerCode} 계좌가 없습니다.`
                  : "연결된 Paper 계좌가 없습니다."}
                <br />
                <Typography.Link href={userRoutes.accounts}>
                  내 계좌에서 계좌를 먼저 연결해 주세요.
                </Typography.Link>
              </span>
            }
          />
        ) : (
          <>
            <Card size="small" title="계좌 선택">
              <Space wrap>
                <Select
                  style={{ width: 320 }}
                  loading={accountsQuery.isLoading}
                  placeholder={
                    usesBrokerAccount
                      ? `${brokerCode} 계좌 선택`
                      : "Paper 계좌 선택"
                  }
                  value={selectedAccountId ?? undefined}
                  options={selectableAccounts.map((row) => ({
                    value: row.account_id,
                    label: `${row.account_name}${
                      row.masked_account_number
                        ? ` (${row.masked_account_number})`
                        : ""
                    }${row.is_default ? " (기본)" : ""}`,
                  }))}
                  onChange={(value: number) => {
                    setSelectedAccountId(value);
                    setPage(1);
                  }}
                />
                <Typography.Link href={userRoutes.orders}>
                  전체 주문·체결 보기
                </Typography.Link>
              </Space>
            </Card>

            {!accountReady ? (
              <Alert
                type="info"
                showIcon
                title="계좌를 선택하면 거래내역을 불러옵니다."
              />
            ) : null}

            <Card title={`${brokerCode} 주문 내역`} size="small">
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
                dataSource={rows}
                locale={{ emptyText: "주문 내역이 없습니다." }}
                pagination={{
                  current: page,
                  pageSize,
                  total: rows.length,
                  onChange: setPage,
                  showSizeChanger: false,
                }}
                columns={orderColumns}
              />
            </Card>
          </>
        )}
      </Space>
    </UserPageShell>
  );
}
