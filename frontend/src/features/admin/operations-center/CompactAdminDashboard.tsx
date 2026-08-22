"use client";

import { Card, Space, Tabs, Typography } from "antd";

import { DASHBOARD_TABS } from "./dashboardTabState";
import { DashboardBrokerFilter } from "./DashboardBrokerFilter";
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
    <Space orientation="vertical" size={12} style={{ width: "100%" }}>
      <Card size="small" styles={{ body: { padding: "12px 16px" } }}>
        <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
          <Typography.Text strong>거래소</Typography.Text>
          <DashboardBrokerFilter value={url.broker} onChange={url.setBroker} />
        </Space>
      </Card>

      <Card size="small" styles={{ body: { paddingTop: 8 } }}>
        <Tabs
          activeKey={activeTab}
          onChange={(key) => url.setTab(key as typeof url.tab)}
          items={DASHBOARD_TABS.map((t) => ({
            key: t.key,
            label: t.label,
            children: null,
          }))}
        />

        {activeTab === "summary" ? (
          <DashboardSummaryTab
            enabled
            broker={url.broker}
            summaryPeriod={url.summaryPeriod}
            onSummaryPeriodChange={url.setSummaryPeriod}
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
            onPeriodChange={url.setPeriod}
            onChartChange={url.setChart}
            refreshMs={60_000}
          />
        ) : null}

        {activeTab === "operations" ? (
          <DashboardOperationsTab
            enabled
            broker={url.broker}
            refreshMs={Math.min(refreshMs, 15_000)}
            killActive={killActive}
            systemInfra={systemInfra}
          />
        ) : null}

        <Typography.Text
          type="secondary"
          style={{ display: "block", marginTop: 12, fontSize: 12 }}
        >
          Read-only · 탭별 lazy load · 공통 거래소 필터
        </Typography.Text>
      </Card>
    </Space>
  );
}
