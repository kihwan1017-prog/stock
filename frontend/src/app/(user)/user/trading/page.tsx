"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Space, message } from "antd";

import { PageContainer } from "@/components/common/PageContainer";
import { JsonPanel } from "@/features/user/components/JsonPanel";
import * as userApi from "@/features/user/api/userApi";
import { queryKeys } from "@/lib/query/queryKeys";
import { toApiError } from "@/lib/api/apiError";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

export default function UserTradingPage() {
  const queryClient = useQueryClient();

  const strategy = useQuery({
    queryKey: queryKeys.user.realtimeStrategy(),
    queryFn: userApi.getRealtimeStrategyStatus,
  });
  const execution = useQuery({
    queryKey: queryKeys.user.realtimeExecution(),
    queryFn: userApi.getRealtimeExecutionStatus,
  });
  const runtime = useQuery({
    queryKey: queryKeys.user.strategyRuntime(),
    queryFn: userApi.getStrategyRuntimeStatus,
  });
  const killSwitch = useQuery({
    queryKey: queryKeys.user.killSwitch(),
    queryFn: userApi.getKillSwitch,
  });

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.user.realtimeStrategy() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.user.realtimeExecution() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.user.strategyRuntime() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.user.killSwitch() }),
    ]);
  };

  const startStrategy = useMutation({
    mutationFn: userApi.startRealtimeStrategy,
    onSuccess: async () => {
      message.success("realtime-strategy start");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const stopStrategy = useMutation({
    mutationFn: userApi.stopRealtimeStrategy,
    onSuccess: async () => {
      message.success("realtime-strategy stop");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const startExec = useMutation({
    mutationFn: userApi.startRealtimeExecution,
    onSuccess: async () => {
      message.success("realtime-execution start");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const stopExec = useMutation({
    mutationFn: userApi.stopRealtimeExecution,
    onSuccess: async () => {
      message.success("realtime-execution stop");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <PageContainer
      title="자동매매"
      description="realtime-strategy / realtime-execution / strategy-runtime / kill-switch API 연동"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <UnimplementedNotice
          feature="사용자별 자동매매 스위치"
          reason="멀티유저 스코프 on/off API는 없습니다. 아래는 서버 전역 realtime API입니다. Kill Switch 활성/비활성 POST는 Admin Key가 필요합니다."
          relatedApis={[
            "POST /api/v1/realtime-strategy/start|stop",
            "GET /api/v1/risk/kill-switch",
          ]}
        />
        <Space wrap>
          <Button type="primary" onClick={() => startStrategy.mutate()} loading={startStrategy.isPending}>
            Strategy Start
          </Button>
          <Button onClick={() => stopStrategy.mutate()} loading={stopStrategy.isPending}>
            Strategy Stop
          </Button>
          <Button type="primary" onClick={() => startExec.mutate()} loading={startExec.isPending}>
            Execution Start
          </Button>
          <Button onClick={() => stopExec.mutate()} loading={stopExec.isPending}>
            Execution Stop
          </Button>
        </Space>
        <JsonPanel
          title="GET /api/v1/realtime-strategy/status"
          loading={strategy.isLoading}
          error={strategy.error ? toApiError(strategy.error) : null}
          data={strategy.data}
        />
        <JsonPanel
          title="GET /api/v1/realtime-execution/status"
          loading={execution.isLoading}
          error={execution.error ? toApiError(execution.error) : null}
          data={execution.data}
        />
        <JsonPanel
          title="GET /api/v1/strategy-runtime/status"
          loading={runtime.isLoading}
          error={runtime.error ? toApiError(runtime.error) : null}
          data={runtime.data}
        />
        <JsonPanel
          title="GET /api/v1/risk/kill-switch"
          loading={killSwitch.isLoading}
          error={killSwitch.error ? toApiError(killSwitch.error) : null}
          data={killSwitch.data}
        />
      </Space>
    </PageContainer>
  );
}
