"use client";

import { Card, Tabs, Typography } from "antd";

import { DASHBOARD_TABS } from "./dashboardTabState";
import { DashboardOperationsTab } from "./DashboardOperationsTab";
import { DashboardPerformanceTab } from "./DashboardPerformanceTab";
import { DashboardSummaryTab } from "./DashboardSummaryTab";
import { useDashboardUrlState } from "./useDashboardUrlState";

type Props = {
  refreshMs?: number;
  killActive?: boolean;
  systemInfra?: React.ReactNode;
};

export function CompactAdminDashboard({
  refreshMs = 20_000,
  killActive = false,
  systemInfra,
}: Props) {
  const url = useDashboardUrlState();
  const activeTab = url.tab;

  return (
    <Card
      size="small"
      styles={{ body: { paddingTop: 8 } }}
    >
      <Tabs
        activeKey={activeTab}
        onChange={(key) =>
          url.setTab(key as typeof url.tab)
        }
        items={DASHBOARD_TABS.map((t) => ({
          key: t.key,
          label: t.label,
          children: null,
        }))}
      />

      {activeTab === "summary" ? (
        <DashboardSummaryTab
          enabled
          refreshMs={refreshMs}
          killActive={killActive}
        />
      ) : null}

      {activeTab === "performance" ? (
        <DashboardPerformanceTab
          enabled
          broker={url.broker}
          period={url.period}
          chart={url.chart}
          onBrokerChange={url.setBroker}
          onPeriodChange={url.setPeriod}
          onChartChange={url.setChart}
          refreshMs={60_000}
        />
      ) : null}

      {activeTab === "operations" ? (
        <DashboardOperationsTab
          enabled
          refreshMs={Math.min(refreshMs, 15_000)}
          killActive={killActive}
          systemInfra={systemInfra}
        />
      ) : null}

      <Typography.Text
        type="secondary"
        style={{ display: "block", marginTop: 12, fontSize: 12 }}
      >
        Read-only · 탭별 lazy load · 비활성 탭 API 호출 없음
      </Typography.Text>
    </Card>
  );
}
