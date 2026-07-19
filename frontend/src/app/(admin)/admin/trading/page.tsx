"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminTradingPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const strategy = useQuery({
    queryKey: queryKeys.admin.realtimeStrategy(),
    queryFn: adminApi.getRealtimeStrategyStatus,
  });
  const execution = useQuery({
    queryKey: queryKeys.admin.realtimeExecution(),
    queryFn: adminApi.getRealtimeExecutionStatus,
  });
  const sessions = useQuery({
    queryKey: queryKeys.admin.realtimeSessions(),
    queryFn: adminApi.getRealtimeSessionsStatus,
  });
  const runtime = useQuery({
    queryKey: queryKeys.admin.strategyRuntime(),
    queryFn: adminApi.getStrategyRuntimeStatus,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: queryKeys.admin.realtimeStrategy() });
    void qc.invalidateQueries({ queryKey: queryKeys.admin.realtimeExecution() });
    void qc.invalidateQueries({ queryKey: queryKeys.admin.realtimeSessions() });
  };

  const startStrategy = useMutation({
    mutationFn: adminApi.startRealtimeStrategy,
    onSuccess: () => {
      message.success("전략 러너 시작");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const stopStrategy = useMutation({
    mutationFn: adminApi.stopRealtimeStrategy,
    onSuccess: () => {
      message.success("전략 러너 중지");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const startExec = useMutation({
    mutationFn: adminApi.startRealtimeExecution,
    onSuccess: () => {
      message.success("체결 러너 시작");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const stopExec = useMutation({
    mutationFn: adminApi.stopRealtimeExecution,
    onSuccess: () => {
      message.success("체결 러너 중지");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell
      title="자동매매관리"
      description="realtime-strategy · realtime-execution · realtime-sessions · strategy-runtime"
      extra={
        <Space wrap>
          <Button type="primary" loading={startStrategy.isPending} onClick={() => startStrategy.mutate()}>
            전략 Start
          </Button>
          <Button danger loading={stopStrategy.isPending} onClick={() => stopStrategy.mutate()}>
            전략 Stop
          </Button>
          <Button type="primary" loading={startExec.isPending} onClick={() => startExec.mutate()}>
            체결 Start
          </Button>
          <Button danger loading={stopExec.isPending} onClick={() => stopExec.mutate()}>
            체결 Stop
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <AdminJsonCard
          title="GET /realtime-strategy/status"
          loading={strategy.isLoading}
          error={strategy.error ? toApiError(strategy.error) : null}
          data={strategy.data}
        />
        <AdminJsonCard
          title="GET /realtime-execution/status"
          loading={execution.isLoading}
          error={execution.error ? toApiError(execution.error) : null}
          data={execution.data}
        />
        <AdminJsonCard
          title="GET /realtime-sessions/status"
          loading={sessions.isLoading}
          error={sessions.error ? toApiError(sessions.error) : null}
          data={sessions.data}
        />
        <AdminJsonCard
          title="GET /strategy-runtime/status"
          loading={runtime.isLoading}
          error={runtime.error ? toApiError(runtime.error) : null}
          data={runtime.data}
        />
      </Space>
    </AdminPageShell>
  );
}
