"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Form, Input, InputNumber, Space, Typography } from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminAccountsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [paperAccountId, setPaperAccountId] = useState<number | null>(null);

  const broker = useQuery({
    queryKey: queryKeys.admin.brokerAccount(),
    queryFn: adminApi.getBrokerAccount,
  });
  const paperAccounts = useQuery({
    queryKey: queryKeys.admin.paperAccounts(),
    queryFn: () => adminApi.listPaperAccounts({ limit: 100 }),
  });
  const selectedId = paperAccountId ?? 0;
  const positions = useQuery({
    queryKey: queryKeys.admin.paperPositions(selectedId),
    queryFn: () => adminApi.getPaperPositions(selectedId),
    enabled: selectedId > 0,
  });
  const liveHistory = useQuery({
    queryKey: queryKeys.admin.liveTransitionHistory(),
    queryFn: adminApi.getLiveTransitionHistory,
  });

  const accountRows = useMemo(
    () => extractRows(paperAccounts.data) as Record<string, unknown>[],
    [paperAccounts.data],
  );

  const createPaper = useMutation({
    mutationFn: adminApi.createPaperAccount,
    onSuccess: (data) => {
      message.success("페이퍼 계좌 생성 완료");
      const created = data as { account_id?: number };
      if (created.account_id) {
        setPaperAccountId(Number(created.account_id));
      }
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.paperAccounts(),
      });
    },
    onError: (err) => message.error(toApiError(err).message),
  });
  const syncKiwoom = useMutation({
    mutationFn: adminApi.syncKiwoomAccount,
    onSuccess: () => {
      message.success("키움 계좌 동기화 요청 완료");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.brokerAccount(),
      });
    },
    onError: (err) => message.error(toApiError(err).message),
  });

  const positionRows = extractRows(positions.data);

  return (
    <AdminPageShell
      title="계좌관리"
      description="paper-accounts 목록 · 생성 · 포지션 · broker/account · live-transition"
      extra={
        <Space wrap>
          <PermissionButton
            permission="trading:write"
            loading={syncKiwoom.isPending}
            onClick={() => syncKiwoom.mutate()}
          >
            키움 계좌 동기화
          </PermissionButton>
          <Button onClick={() => void broker.refetch()}>브로커 새로고침</Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
          기본은 Paper Trading. 실잔고 조회/주문은{" "}
          <code>KIWOOM_LIVE_ORDER_ENABLED</code> + live-transition 승인 후에만
          가능합니다. <code>GET /broker/account</code>은 Paper 스냅샷입니다.
        </Typography.Paragraph>

        <AdminJsonCard
          title="GET /broker/account (Paper 스냅샷)"
          loading={broker.isLoading}
          error={broker.error ? toApiError(broker.error) : null}
          data={broker.data}
        />

        <Form
          layout="inline"
          onFinish={(v: { account_name: string; initial_cash: number }) =>
            createPaper.mutate(v)
          }
          style={{ marginBottom: 8 }}
        >
          <Form.Item
            name="account_name"
            rules={[{ required: true, message: "계좌명 필요" }]}
          >
            <Input placeholder="account_name" />
          </Form.Item>
          <Form.Item
            name="initial_cash"
            rules={[{ required: true }]}
            initialValue={10_000_000}
          >
            <InputNumber min={1} placeholder="initial_cash" style={{ width: 160 }} />
          </Form.Item>
          <PermissionButton
            permission="trading:write"
            type="primary"
            htmlType="submit"
            loading={createPaper.isPending}
          >
            페이퍼 계좌 등록
          </PermissionButton>
        </Form>

        <AdminDataTable
          title="GET /paper-accounts"
          loading={paperAccounts.isLoading}
          error={paperAccounts.error ? toApiError(paperAccounts.error) : null}
          rowKey={(r) => cell(r.account_id ?? JSON.stringify(r))}
          columns={[
            { title: "account_id", dataIndex: "account_id", sorter: true },
            { title: "name", dataIndex: "account_name" },
            { title: "cash", dataIndex: "available_cash" },
            { title: "currency", dataIndex: "currency_code" },
            {
              title: "포지션",
              render: (_, row) => (
                <Button
                  size="small"
                  onClick={() => setPaperAccountId(Number(row.account_id))}
                >
                  조회
                </Button>
              ),
            },
          ]}
          dataSource={accountRows}
        />

        {selectedId > 0 ? (
          <AdminDataTable
            title={`GET /paper-accounts/${selectedId}/positions`}
            loading={positions.isLoading}
            error={positions.error ? toApiError(positions.error) : null}
            rowKey={(r) => cell(r.symbol ?? r.position_id ?? JSON.stringify(r))}
            columns={[
              { title: "심볼", dataIndex: "symbol", sorter: true },
              { title: "수량", dataIndex: "quantity" },
              { title: "평균단가", dataIndex: "average_entry_price" },
              {
                title: "원본",
                render: (_, row) => cell(row),
              },
            ]}
            dataSource={positionRows}
          />
        ) : null}

        <AdminJsonCard
          title="GET /broker/live-transition/history (Admin Key)"
          loading={liveHistory.isLoading}
          error={liveHistory.error ? toApiError(liveHistory.error) : null}
          data={liveHistory.data}
        />
      </Space>
    </AdminPageShell>
  );
}
