"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Space, Table, Tag } from "antd";

import { UserPageShell } from "@/features/user/components/UserPageShell";
import { asRecord } from "@/features/admin/utils/dataHelpers";
import * as userApi from "@/features/user/api/userApi";

/**
 * User — Upbit 소액 LIVE 검증 읽기 전용.
 * 실행·취소·ARM 변경 불가.
 */
export default function UserUpbitLiveValidationPage() {
  const runsQuery = useQuery({
    queryKey: ["user", "upbit-live-validation-runs"],
    queryFn: () => userApi.listUpbitLiveValidationRuns(),
    refetchInterval: 20_000,
  });
  const accountsQuery = useQuery({
    queryKey: ["user", "live-order-status"],
    queryFn: () => userApi.listMyLiveOrderStatus(),
  });

  const items =
    (asRecord(runsQuery.data)?.items as Record<string, unknown>[] | undefined) ??
    [];
  const accounts =
    (asRecord(accountsQuery.data)?.items as
      | Record<string, unknown>[]
      | undefined) ??
    (Array.isArray(accountsQuery.data)
      ? (accountsQuery.data as Record<string, unknown>[])
      : []);

  return (
    <UserPageShell
      title="업비트 LIVE 검증"
      description="본인 계좌의 소액 LIVE 검증 상태만 조회합니다. 실행·취소는 관리자만 가능합니다."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="읽기 전용"
          description="LIVE ON/OFF·ARM·주문 실행은 Admin 전용입니다."
        />

        <Card title="내 UBA LIVE/ARM" size="small" loading={accountsQuery.isLoading}>
          <Table
            size="small"
            rowKey={(r) => String(r.user_broker_account_id)}
            pagination={false}
            dataSource={accounts.filter(
              (a) => String(a.broker_code || "").toUpperCase() === "UPBIT",
            )}
            columns={[
              { title: "UBA", dataIndex: "user_broker_account_id" },
              {
                title: "LIVE",
                dataIndex: "live_order_enabled",
                render: (v: boolean) => (
                  <Tag color={v ? "green" : "default"}>
                    {v ? "ON" : "OFF"}
                  </Tag>
                ),
              },
              {
                title: "ARMED",
                dataIndex: "live_armed",
                render: (v: boolean) => (
                  <Tag color={v ? "orange" : "default"}>
                    {v ? "ARMED" : "DISARMED"}
                  </Tag>
                ),
              },
            ]}
          />
        </Card>

        <Card title="검증 Run 이력" size="small" loading={runsQuery.isLoading}>
          <Table
            size="small"
            rowKey={(r) => String(r.run_id)}
            dataSource={items}
            columns={[
              { title: "run_id", dataIndex: "run_id" },
              { title: "status", dataIndex: "status" },
              { title: "market", dataIndex: "market" },
              { title: "side", dataIndex: "side" },
              { title: "order_id", dataIndex: "order_id" },
              {
                title: "live",
                dataIndex: "execute_live",
                render: (v: boolean) => (v ? "Y" : "N"),
              },
            ]}
          />
        </Card>
      </Space>
    </UserPageShell>
  );
}
