"use client";

import { Alert, Space } from "antd";

import { GuidedUpbitLiveSmokePanel } from "@/features/user/trading/GuidedUpbitLiveSmokePanel";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { useQuery } from "@tanstack/react-query";
import { Table, Tag, Card } from "antd";

import { asRecord } from "@/shared/utils/dataHelpers";
import * as userApi from "@/features/user/api/userApi";

/**
 * User — Upbit Guided LIVE Smoke + 이력.
 */
export default function UserUpbitLiveValidationPage() {
  const runsQuery = useQuery({
    queryKey: ["user", "upbit-live-validation-runs"],
    queryFn: () => userApi.listUpbitLiveValidationRuns(),
    refetchInterval: 20_000,
  });

  const items =
    (asRecord(runsQuery.data)?.items as Record<string, unknown>[] | undefined) ??
    [];

  return (
    <UserPageShell
      title="업비트 LIVE 검증"
      description="계좌 단위 Pre-flight → Preview → 확인문구 → (선택) 실주문. Cursor 기본은 Dry-run만."
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="경로: 매매(주문 실행) → 업비트 LIVE 검증"
          description="실주문 Flag/ARM/Unlock은 이 작업에서 켜지 않습니다. 확인문구 불일치 시 주문 API 호출 0."
        />

        <GuidedUpbitLiveSmokePanel />

        <Card title="검증 Run 이력" size="small" loading={runsQuery.isLoading}>
          <Table
            size="small"
            rowKey={(r) => String(r.run_id)}
            dataSource={items}
            columns={[
              { title: "run_id", dataIndex: "run_id" },
              {
                title: "status",
                dataIndex: "display_status",
                render: (v: unknown, row: Record<string, unknown>) => {
                  const display = String(
                    v ?? row.status ?? "",
                  ).toUpperCase();
                  const broker = String(
                    row.broker_order_status ?? "",
                  ).toUpperCase();
                  const isInternalRetire =
                    display === "CANCELED" &&
                    (broker === "NOT_SUBMITTED" || broker === "");
                  if (isInternalRetire) {
                    return (
                      <Tag color="default">
                        내부 폐기됨 (CANCELED)
                      </Tag>
                    );
                  }
                  const color =
                    display === "WAIT" || display === "SUBMITTED"
                      ? "processing"
                      : display === "FILLED"
                        ? "success"
                        : display === "AMBIGUOUS"
                          ? "warning"
                          : display === "NOT_SUBMITTED" ||
                              display === "QUEUED"
                            ? "default"
                            : display === "CANCELED"
                              ? "default"
                              : "default";
                  return <Tag color={color}>{display || "-"}</Tag>;
                },
              },
              {
                title: "broker",
                dataIndex: "broker_order_status",
                render: (v: unknown, row: Record<string, unknown>) => {
                  const broker = String(v ?? "NOT_SUBMITTED").toUpperCase();
                  const display = String(
                    row.display_status ?? "",
                  ).toUpperCase();
                  // UUID 있는데 NOT_SUBMITTED면 display 우선
                  if (
                    broker === "NOT_SUBMITTED" &&
                    row.broker_uuid_masked &&
                    display &&
                    display !== "NOT_SUBMITTED"
                  ) {
                    return <Tag color="processing">{display}</Tag>;
                  }
                  const label =
                    broker === "OPEN"
                      ? "WAIT"
                      : broker === "ACCEPTED"
                        ? "SUBMITTED"
                        : broker;
                  return <Tag>{label}</Tag>;
                },
              },
              { title: "order_id", dataIndex: "order_id" },
              {
                title: "UUID",
                dataIndex: "broker_uuid_masked",
                render: (v: unknown) => String(v ?? "-"),
              },
              { title: "market", dataIndex: "market" },
              { title: "side", dataIndex: "side" },
              {
                title: "live",
                dataIndex: "execute_live",
                render: (v: boolean) => (
                  <Tag color={v ? "red" : "default"}>{v ? "Y" : "N"}</Tag>
                ),
              },
            ]}
          />
        </Card>
      </Space>
    </UserPageShell>
  );
}
