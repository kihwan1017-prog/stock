"use client";

/**
 * Compact tabbed Operations Center — 요약 / 성과 / 운영.
 */

import { useQuery } from "@tanstack/react-query";
import { Alert, Space, Tag, Typography } from "antd";
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
          <Tag color="blue">조회 전용</Tag>
          <Typography.Text type="secondary">
            오늘 운영 한눈에 보기 · 마지막 갱신: {lastRefresh}
            {summaryQuery.isFetching ? " (갱신 중…)" : ""}
          </Typography.Text>
        </Space>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          시스템: {String(system.health ?? "—")}
        </Typography.Text>
      </Space>

      <Alert
        type={kill.active ? "error" : "info"}
        showIcon
        title={
          kill.active
            ? "조치 필요 — Kill Switch 활성"
            : "5초 체크: 자동매매가 돌아가는가? 손익은? 해야 할 일이 있는가?"
        }
        description={
          kill.active
            ? "신규 매수가 차단된 상태입니다. 안전 제어·계좌 화면에서 원인을 확인하세요."
            : "상세 주문·슬롯·리스크는 자동매매 / 설정 메뉴의 대표 화면에서 확인합니다."
        }
        style={{ marginBottom: 0 }}
      />

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
