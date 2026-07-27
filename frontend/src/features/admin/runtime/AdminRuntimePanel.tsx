"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Space,
  Table,
  Tag,
  Typography,
  message as antdMessage,
} from "antd";

import type { StrategyRuntimeItem } from "@/features/admin/api/adminApi";
import * as adminApi from "@/features/admin/api/adminApi";
import { extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";

function formatTs(value: string | null | undefined): string {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("ko-KR");
  } catch {
    return String(value);
  }
}

/**
 * STEP 8-5-5 — Scope Runtime 관리 (전역 슬롯 없음).
 */
export function AdminRuntimePanel() {
  const [messageApi, contextHolder] = antdMessage.useMessage();
  const queryClient = useQueryClient();

  const listQuery = useQuery({
    queryKey: ["admin", "runtimes"],
    queryFn: () => adminApi.listAdminRuntimes(),
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["admin", "runtimes"] });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "strategy-runtime"],
    });
  };

  const action = useMutation({
    mutationFn: async (input: {
      type: "pause" | "resume" | "reload" | "stop";
      scopeKey: string;
    }) => {
      if (input.type === "pause") {
        return adminApi.pauseAdminRuntime(input.scopeKey);
      }
      if (input.type === "resume") {
        return adminApi.resumeAdminRuntime(input.scopeKey);
      }
      if (input.type === "reload") {
        return adminApi.reloadAdminRuntime(input.scopeKey);
      }
      return adminApi.stopAdminRuntime(input.scopeKey);
    },
    onSuccess: async () => {
      messageApi.success("Runtime 조치를 적용했습니다.");
      await invalidate();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const rows = extractRows(listQuery.data) as unknown as StrategyRuntimeItem[];

  return (
    <Card size="small" title="Scope Strategy Runtime" loading={listQuery.isLoading}>
      {contextHolder}
      <Typography.Paragraph type="secondary">
        전역 Runtime 슬롯은 제거되었습니다. Scope별로 Pause / Resume / Reload /
        Stop 합니다.
      </Typography.Paragraph>
      <Table<StrategyRuntimeItem>
        size="small"
        rowKey={(r) => r.scope_key}
        dataSource={rows}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: "User", dataIndex: "user_id", width: 70 },
          { title: "Broker", dataIndex: "broker_code", width: 80 },
          { title: "Market", dataIndex: "market_type", width: 80 },
          {
            title: "계좌",
            key: "acct",
            render: (_: unknown, r) =>
              r.account_kind === "PAPER"
                ? `paper:${r.account_id}`
                : `uba:${r.account_id}`,
          },
          { title: "Strategy", dataIndex: "strategy_id", width: 90 },
          {
            title: "상태",
            dataIndex: "status",
            render: (v: string) => <Tag>{v}</Tag>,
          },
          {
            title: "Pause 사유",
            dataIndex: "pause_reason",
            render: (v: string | null) => v ?? "-",
          },
          {
            title: "최근 시작",
            dataIndex: "last_started_at",
            render: formatTs,
          },
          {
            title: "조치",
            key: "actions",
            render: (_: unknown, row) => (
              <Space size={4} wrap>
                <Button
                  size="small"
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate({
                      type: "pause",
                      scopeKey: row.scope_key,
                    })
                  }
                >
                  Pause
                </Button>
                <Button
                  size="small"
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate({
                      type: "resume",
                      scopeKey: row.scope_key,
                    })
                  }
                >
                  Resume
                </Button>
                <Button
                  size="small"
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate({
                      type: "reload",
                      scopeKey: row.scope_key,
                    })
                  }
                >
                  Reload
                </Button>
                <Button
                  size="small"
                  danger
                  disabled={action.isPending}
                  onClick={() =>
                    action.mutate({
                      type: "stop",
                      scopeKey: row.scope_key,
                    })
                  }
                >
                  Stop
                </Button>
              </Space>
            ),
          },
        ]}
      />
    </Card>
  );
}
