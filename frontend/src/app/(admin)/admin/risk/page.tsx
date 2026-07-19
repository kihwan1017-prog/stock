"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Space } from "antd";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminRiskPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();

  const kill = useQuery({
    queryKey: queryKeys.admin.killSwitch(),
    queryFn: adminApi.getKillSwitch,
  });
  const daily = useQuery({
    queryKey: queryKeys.admin.dailyLoss(),
    queryFn: adminApi.getDailyLossStatus,
  });
  const policies = useQuery({
    queryKey: queryKeys.admin.riskPolicies(),
    queryFn: adminApi.listRiskPolicies,
  });
  const dash = useQuery({
    queryKey: queryKeys.dashboard.risk(),
    queryFn: () => adminApi.getRiskDashboard(),
  });

  const activate = useMutation({
    mutationFn: () => adminApi.activateKillSwitch(),
    onSuccess: () => {
      message.success("Kill Switch 활성화");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.killSwitch() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });
  const deactivate = useMutation({
    mutationFn: () => adminApi.deactivateKillSwitch(),
    onSuccess: () => {
      message.success("Kill Switch 해제");
      void qc.invalidateQueries({ queryKey: queryKeys.admin.killSwitch() });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell
      title="Risk 관리"
      description="kill-switch · daily-loss · risk-policies · dashboard/risk"
      extra={
        <Space>
          <Button danger loading={activate.isPending} onClick={() => activate.mutate()}>
            Kill Switch ON
          </Button>
          <Button loading={deactivate.isPending} onClick={() => deactivate.mutate()}>
            Kill Switch OFF
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <AdminJsonCard
          title="GET /risk/kill-switch"
          loading={kill.isLoading}
          error={kill.error ? toApiError(kill.error) : null}
          data={kill.data}
        />
        <AdminJsonCard
          title="GET /risk/daily-loss/status"
          loading={daily.isLoading}
          error={daily.error ? toApiError(daily.error) : null}
          data={daily.data}
        />
        <AdminDataTable
          title="GET /risk-policies"
          loading={policies.isLoading}
          error={policies.error ? toApiError(policies.error) : null}
          rowKey={(r) => cell(r.policy_id ?? r.policy_name ?? JSON.stringify(r))}
          columns={[
            { title: "policy_id", dataIndex: "policy_id", sorter: true },
            { title: "name", dataIndex: "policy_name" },
            { title: "mode", dataIndex: "position_sizing_mode" },
            { title: "stop_loss", dataIndex: "stop_loss_ratio" },
          ]}
          dataSource={extractRows(policies.data)}
        />
        <AdminJsonCard
          title="GET /dashboard/risk"
          loading={dash.isLoading}
          error={dash.error ? toApiError(dash.error) : null}
          data={dash.data}
        />
      </Space>
    </AdminPageShell>
  );
}
