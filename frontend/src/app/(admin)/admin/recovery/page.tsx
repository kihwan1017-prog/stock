"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { RecoverySchedulerPanel } from "@/features/admin/recovery/RecoverySchedulerPanel";
import { RecoveryConflictPanel } from "@/features/admin/recovery/RecoveryConflictPanel";
import { RecoveryDistributedLockPanel } from "@/features/admin/recovery/RecoveryDistributedLockPanel";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminRecoveryPage() {
  const { message, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [brokerFilter, setBrokerFilter] = useState<string | undefined>();
  const [paperAccountId, setPaperAccountId] = useState<number | null>(null);
  const [detailId, setDetailId] = useState<number | null>(null);

  const statusQuery = useQuery({
    queryKey: queryKeys.admin.brokerRecoveryStatus(),
    queryFn: () => adminApi.getAdminRecoveryStatus(),
    refetchInterval: (query) => {
      const data = asRecord(query.state.data);
      return data?.running ? 2000 : false;
    },
  });

  const runsQuery = useQuery({
    queryKey: ["admin", "recovery-runs", brokerFilter ?? "all"],
    queryFn: () =>
      adminApi.listAdminRecoveryRuns({
        broker_code: brokerFilter,
        limit: 50,
      }),
  });

  const detailQuery = useQuery({
    queryKey: ["admin", "recovery-run", detailId],
    queryFn: () => adminApi.getAdminRecoveryRun(detailId!),
    enabled: detailId != null && detailId > 0,
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.admin.brokerRecoveryStatus(),
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "recovery-runs"],
    });
  };

  const runAll = useMutation({
    mutationFn: () => adminApi.runAdminRecovery({ concurrency: 3 }),
    onSuccess: async (result) => {
      const row = asRecord(result);
      message.success(
        row?.success
          ? "전체 Recovery 완료"
          : "Recovery 실행됨 (일부 실패/검토 필요)",
      );
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const runBroker = useMutation({
    mutationFn: (code: string) => adminApi.runAdminBrokerRecovery(code),
    onSuccess: async () => {
      message.success("Broker Recovery 요청 완료");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const runAccount = useMutation({
    mutationFn: (id: number) =>
      adminApi.runAdminAccountRecovery(id, "PAPER"),
    onSuccess: async () => {
      message.success("계좌 Recovery 요청 완료");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const status = asRecord(statusQuery.data);
  const latest = asRecord(status?.latest_run);
  const accountStates = extractRows(
    status?.account_states
      ? { items: status.account_states }
      : statusQuery.data,
  );
  const runRows = extractRows(runsQuery.data);
  const busy =
    runAll.isPending || runBroker.isPending || runAccount.isPending;

  return (
    <AdminPageShell
      title="장애·복구"
      description="현재 장애 · 자동 복구 · 조치 필요를 구분합니다. 과거 복구 완료 건은 현재 장애로 보이지 않도록 이력을 별도 확인하세요."
      extra={
        <Space wrap>
          <Link href={adminRoutes.operations}>
            <Button>시스템 운영</Button>
          </Link>
          <Link href={adminRoutes.monitoring}>
            <Button>시스템 상태</Button>
          </Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          title="복구 상태 보는 법"
          description="현재 장애 → 자동 복구 중 → 복구 완료 → 사용자 조치 필요. 이미 복구된(recovered) 이슈는 현재 장애처럼 취급하지 마세요. Secret/계좌번호 원문은 표시하지 않습니다."
        />

        <RecoverySchedulerPanel />

        <RecoveryDistributedLockPanel
          onOpenRun={(id) => setDetailId(id)}
        />

        <RecoveryConflictPanel />

        <Card size="small" title="실행">
          <Space wrap>
            <Button
              type="primary"
              danger
              loading={runAll.isPending}
              disabled={busy}
              onClick={() =>
                modal.confirm({
                  title: "전체 Recovery를 실행할까요?",
                  onOk: () => runAll.mutateAsync(),
                })
              }
            >
              전체 복구
            </Button>
            <Button
              loading={runBroker.isPending}
              disabled={busy}
              onClick={() => runBroker.mutate("KIWOOM")}
            >
              키움 복구
            </Button>
            <Button
              loading={runBroker.isPending}
              disabled={busy}
              onClick={() => runBroker.mutate("UPBIT")}
            >
              업비트 복구
            </Button>
            <Button
              loading={runBroker.isPending}
              disabled={busy}
              onClick={() => runBroker.mutate("PAPER")}
            >
              Paper 복구
            </Button>
            <InputNumber
              min={1}
              placeholder="Paper 계좌 ID"
              value={paperAccountId ?? undefined}
              onChange={(v) =>
                setPaperAccountId(typeof v === "number" ? v : null)
              }
            />
            <Button
              disabled={busy || !paperAccountId}
              loading={runAccount.isPending}
              onClick={() => {
                if (paperAccountId) runAccount.mutate(paperAccountId);
              }}
            >
              계좌 단위 복구
            </Button>
          </Space>
        </Card>

        <Card size="small" title="현재 상태" loading={statusQuery.isLoading}>
          <Descriptions size="small" column={2} bordered>
            <Descriptions.Item label="실행 중">
              {status?.running ? (
                <Tag color="processing">RUNNING</Tag>
              ) : (
                <Tag>IDLE</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="최근 오류">
              {cell(status?.last_error ?? "—")}
            </Descriptions.Item>
            <Descriptions.Item label="최근 Run">
              {cell(latest?.broker_recovery_run_id ?? "—")}
            </Descriptions.Item>
            <Descriptions.Item label="최근 상태">
              {cell(latest?.status_code ?? "—")}
            </Descriptions.Item>
            <Descriptions.Item label="주문검사">
              {cell(latest?.open_orders_checked ?? 0)}
            </Descriptions.Item>
            <Descriptions.Item label="주문수정">
              {cell(latest?.orders_updated ?? 0)}
            </Descriptions.Item>
            <Descriptions.Item label="체결생성">
              {cell(latest?.fills_created ?? 0)}
            </Descriptions.Item>
            <Descriptions.Item label="잔고/포지션">
              {cell(latest?.balances_updated ?? 0)} /{" "}
              {cell(latest?.positions_updated ?? 0)}
            </Descriptions.Item>
            <Descriptions.Item label="Conflict">
              {cell(latest?.conflicts_found ?? 0)}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Card size="small" title="계좌 Recovery 상태">
          <Table
            size="small"
            pagination={{ pageSize: 8 }}
            rowKey={(r) =>
              `${asRecord(r)?.broker_code}-${asRecord(r)?.paper_account_id}-${asRecord(r)?.user_broker_account_id}`
            }
            dataSource={accountStates}
            locale={{ emptyText: "상태 없음" }}
            columns={[
              { title: "거래소/증권사", dataIndex: "broker_code", render: cell },
              { title: "User", dataIndex: "user_id", width: 80, render: cell },
              {
                title: "Paper",
                dataIndex: "paper_account_id",
                width: 90,
                render: cell,
              },
              {
                title: "UBA",
                dataIndex: "user_broker_account_id",
                width: 90,
                render: cell,
              },
              {
                title: "상태",
                dataIndex: "recovery_status",
                render: (v: unknown) => <Tag>{cell(v)}</Tag>,
              },
              {
                title: "거래차단",
                dataIndex: "trading_paused",
                width: 90,
                render: (v: unknown) =>
                  v ? <Tag color="error">Y</Tag> : <Tag>N</Tag>,
              },
              {
                title: "오류",
                dataIndex: "last_error_summary",
                render: cell,
              },
            ]}
          />
        </Card>

        <Card
          size="small"
          title="실행 이력"
          extra={
            <Select
              allowClear
              placeholder="Broker 필터"
              style={{ width: 140 }}
              value={brokerFilter}
              onChange={(v) => setBrokerFilter(v)}
              options={[
                { value: "KIWOOM", label: "KIWOOM" },
                { value: "UPBIT", label: "UPBIT" },
                { value: "PAPER_STOCK", label: "PAPER_STOCK" },
                { value: "PAPER_CRYPTO", label: "PAPER_CRYPTO" },
              ]}
            />
          }
        >
          <Table
            size="small"
            loading={runsQuery.isLoading}
            pagination={{ pageSize: 10 }}
            rowKey={(r) => String(asRecord(r)?.broker_recovery_run_id)}
            dataSource={runRows}
            onRow={(row) => ({
              onClick: () =>
                setDetailId(Number(asRecord(row)?.broker_recovery_run_id)),
            })}
            columns={[
              {
                title: "ID",
                dataIndex: "broker_recovery_run_id",
                width: 70,
                render: cell,
              },
              { title: "거래소/증권사", dataIndex: "broker_code", render: cell },
              { title: "Trigger", dataIndex: "trigger_type", render: cell },
              {
                title: "상태",
                dataIndex: "status_code",
                render: (v: unknown) => <Tag>{cell(v)}</Tag>,
              },
              {
                title: "검사",
                dataIndex: "open_orders_checked",
                width: 70,
                render: cell,
              },
              {
                title: "수정",
                dataIndex: "orders_updated",
                width: 70,
                render: cell,
              },
              {
                title: "불일치",
                dataIndex: "conflicts_found",
                width: 90,
                render: cell,
              },
              { title: "오류", dataIndex: "error_message", render: cell },
            ]}
          />
          {detailId ? (
            <Typography.Paragraph
              style={{ marginTop: 12 }}
              type="secondary"
            >
              상세 Run #{detailId}:{" "}
              {detailQuery.isLoading
                ? "로딩…"
                : JSON.stringify(detailQuery.data ?? {}, null, 0).slice(
                    0,
                    500,
                  )}
            </Typography.Paragraph>
          ) : null}
        </Card>
      </Space>
    </AdminPageShell>
  );
}
