"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminKiwoomPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const config = useQuery({
    queryKey: queryKeys.admin.kiwoomConfig(),
    queryFn: adminApi.getKiwoomConfiguration,
  });
  const broker = useQuery({
    queryKey: queryKeys.admin.brokerAccount(),
    queryFn: adminApi.getBrokerAccount,
  });
  const liveHistory = useQuery({
    queryKey: queryKeys.admin.liveTransitionHistory(),
    queryFn: adminApi.getLiveTransitionHistory,
  });

  const testToken = useMutation({
    mutationFn: adminApi.testKiwoomToken,
    onSuccess: () => message.success("토큰 테스트 완료"),
    onError: (e) => message.error(toApiError(e).message),
  });
  const sync = useMutation({
    mutationFn: adminApi.syncKiwoomAccount,
    onSuccess: () => {
      message.success("계좌 동기화 완료");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.brokerAccount() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell
      title="키움 API 관리"
      description="kiwoom/configuration · token/test · account sync · live-transition"
      extra={
        <Space>
          <Button loading={testToken.isPending} onClick={() => testToken.mutate()}>
            토큰 테스트
          </Button>
          <Button type="primary" loading={sync.isPending} onClick={() => sync.mutate()}>
            계좌 동기화
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <AdminJsonCard
          title="GET /kiwoom/configuration"
          loading={config.isLoading}
          error={config.error ? toApiError(config.error) : null}
          data={config.data}
        />
        <AdminJsonCard
          title="GET /broker/account"
          loading={broker.isLoading}
          error={broker.error ? toApiError(broker.error) : null}
          data={broker.data}
        />
        <AdminJsonCard
          title="GET /broker/live-transition/history"
          loading={liveHistory.isLoading}
          error={liveHistory.error ? toApiError(liveHistory.error) : null}
          data={liveHistory.data}
        />
      </Space>
    </AdminPageShell>
  );
}
