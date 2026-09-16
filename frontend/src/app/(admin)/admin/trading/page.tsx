"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space } from "antd";
import Link from "next/link";

import { adminRoutes } from "@/config/routes";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { AdminRuntimePanel } from "@/features/admin/runtime/AdminRuntimePanel";
import { AdminRealtimeHubPanel } from "@/features/admin/realtime/AdminRealtimeHubPanel";
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
      title="자동매매 Runtime"
      description="Scope Runtime과 Realtime Hub를 제어합니다. 주문·Outbox 관리는 /admin/orders 입니다."
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
          <Link href={adminRoutes.orders}>주문·Outbox</Link>
          <Link href={adminRoutes.operationsPreflight}>Pre-flight</Link>
          <Link href={adminRoutes.operationsDashboard}>거래 운영 현황</Link>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <AdminRuntimePanel />
        <AdminRealtimeHubPanel />
        <AdminJsonCard
          title="GET /realtime-strategy/status (deprecated → Hub)"
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
          title="GET /strategy-runtime/status (scoped registry)"
          loading={runtime.isLoading}
          error={runtime.error ? toApiError(runtime.error) : null}
          data={runtime.data}
        />
      </Space>
    </AdminPageShell>
  );
}
