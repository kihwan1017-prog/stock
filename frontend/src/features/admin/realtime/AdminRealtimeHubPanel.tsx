"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space, Typography } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import {
  AdminDataTable,
  AdminJsonCard,
} from "@/features/admin/components/AdminPanels";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

/** STEP 8-5-9 — Realtime Hub Scope 패널 (강제 주문/신호 없음) */
export function AdminRealtimeHubPanel() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const connections = useQuery({
    queryKey: queryKeys.admin.realtimeHubConnections(),
    queryFn: adminApi.getRealtimeHubConnections,
  });
  const scopes = useQuery({
    queryKey: queryKeys.admin.realtimeHubScopes(),
    queryFn: adminApi.getRealtimeHubScopes,
  });

  const invalidate = () => {
    void qc.invalidateQueries({
      queryKey: queryKeys.admin.realtimeHubScopes(),
    });
    void qc.invalidateQueries({
      queryKey: queryKeys.admin.realtimeHubConnections(),
    });
  };

  const reconnect = useMutation({
    mutationFn: (scopeKey: string) =>
      adminApi.reconnectRealtimeHubScope(scopeKey),
    onSuccess: () => {
      message.success("Reconnect 요청 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rewarm = useMutation({
    mutationFn: (scopeKey: string) =>
      adminApi.rewarmRealtimeHubScope(scopeKey),
    onSuccess: () => {
      message.success("Rewarm 요청 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const rows = extractRows(scopes.data);

  return (
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Typography.Text type="secondary">
        Shared Hub · Scope Consumer (STEP 8-5-9). 강제 Signal/주문 버튼 없음.
      </Typography.Text>
      <AdminJsonCard
        title="GET /admin/realtime/connections"
        loading={connections.isLoading}
        error={connections.error ? toApiError(connections.error) : null}
        data={connections.data}
        extra={
          <Button size="small" onClick={() => invalidate()}>
            새로고침
          </Button>
        }
      />
      <AdminDataTable
        title="Realtime Scopes"
        loading={scopes.isLoading}
        error={scopes.error ? toApiError(scopes.error) : null}
        rowKey={(r) => cell(r.scope_key ?? JSON.stringify(r))}
        columns={[
          { title: "User", dataIndex: "user_id", width: 70 },
          { title: "계좌", dataIndex: "account_masked", width: 100 },
          { title: "Broker", dataIndex: "broker_code", width: 80 },
          { title: "Strategy", dataIndex: "strategy_id", width: 80 },
          { title: "Ver", dataIndex: "strategy_version", width: 70 },
          { title: "Status", dataIndex: "runtime_status", width: 100 },
          { title: "Warm-up", dataIndex: "warmup_status", width: 110 },
          { title: "Last Signal", dataIndex: "last_signal_at" },
          { title: "Error", dataIndex: "last_error" },
          {
            title: "Actions",
            key: "actions",
            width: 180,
            render: (_: unknown, row: Record<string, unknown>) => {
              const key = String(row.scope_key ?? "");
              if (!key) return "-";
              return (
                <Space size={4}>
                  <Button
                    size="small"
                    loading={reconnect.isPending}
                    onClick={() => reconnect.mutate(key)}
                  >
                    Reconnect
                  </Button>
                  <Button
                    size="small"
                    loading={rewarm.isPending}
                    onClick={() => rewarm.mutate(key)}
                  >
                    Rewarm
                  </Button>
                </Space>
              );
            },
          },
        ]}
        dataSource={rows}
      />
    </Space>
  );
}
