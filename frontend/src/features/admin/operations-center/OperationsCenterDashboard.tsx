"use client";

/**
 * Compact tabbed Operations Center — 요약 / 성과 / 운영.
 */

import { useQuery } from "@tanstack/react-query";
import { Space, Tag, Typography } from "antd";
import { Suspense, useEffect, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord } from "@/features/admin/utils/dataHelpers";
import { queryKeys } from "@/lib/query/queryKeys";

import { CompactAdminDashboard } from "./CompactAdminDashboard";
import { DashboardSystemInfra } from "./DashboardSystemInfra";

function rec(value: unknown): Record<string, unknown> {
  return asRecord(value) ?? {};
}

function usePageVisible(): boolean {
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    const onChange = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", onChange);
    onChange();
    return () => document.removeEventListener("visibilitychange", onChange);
  }, []);
  return visible;
}

type Props = {
  refreshMs?: number;
};

function OperationsCenterDashboardBody({ refreshMs = 20000 }: Props) {
  const pageVisible = usePageVisible();
  const interval =
    pageVisible && refreshMs > 0 ? refreshMs : false;

  const summaryQuery = useQuery({
    queryKey: queryKeys.admin.operationsCenterSummary(),
    queryFn: () => adminApi.getOperationsCenterSummary({ cache_ttl_sec: 3 }),
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const data = rec(summaryQuery.data);
  const system = rec(data.system);
  const safety = rec(data.safety);
  const kill = rec(safety.kill_switch);

  const lastRefresh = data.checked_at
    ? new Date(String(data.checked_at)).toLocaleString("ko-KR")
    : "—";

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
        <Space wrap>
          <Tag color="blue">Read-only</Tag>
          <Typography.Text type="secondary">
            마지막 갱신: {lastRefresh}
            {summaryQuery.isFetching ? " (갱신 중…)" : ""}
          </Typography.Text>
        </Space>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          Health: {String(system.health ?? "—")}
        </Typography.Text>
      </Space>

      <CompactAdminDashboard
        refreshMs={typeof interval === "number" ? interval : 0}
        killActive={Boolean(kill.active)}
        systemInfra={
          <DashboardSystemInfra
            data={data}
            loading={summaryQuery.isLoading}
          />
        }
      />
    </Space>
  );
}

export function OperationsCenterDashboard(props: Props) {
  return (
    <Suspense fallback={<Typography.Text>대시보드 로딩…</Typography.Text>}>
      <OperationsCenterDashboardBody {...props} />
    </Suspense>
  );
}
