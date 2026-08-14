"use client";

/**
 * STEP 8-11A ? Operations Monitoring Dashboard (Read-only).
 * No LIVE ON / ARM / order / Scheduler Resume controls.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Empty,
  Row,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { OPS_DASHBOARD_LABELS as L } from "@/features/admin/ops-monitoring/opsMonitoringLabels";
import { OPERATION_CANONICAL_LINKS } from "@/features/admin/operations/operationCanonicalLinks";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

type RefreshMs = 0 | 5000 | 10000 | 30000 | 60000;

function rec(value: unknown): Record<string, unknown> {
  return asRecord(value) ?? {};
}

function statusColor(status: unknown): string {
  const s = String(status ?? "UNKNOWN").toUpperCase();
  if (
    ["HEALTHY", "RUNNING", "READY", "OK", "VERIFIED", "PASS", "NORMAL"].includes(
      s,
    )
  ) {
    return "success";
  }
  if (["WARNING", "STALE", "PAUSED", "DANGER", "CONFIGURED"].includes(s)) {
    return "warning";
  }
  if (
    ["ERROR", "BLOCKED", "FAILED", "UNHEALTHY", "CRITICAL", "ACTIVE"].includes(
      s,
    )
  ) {
    return "error";
  }
  return "default";
}

function StatusTag({ label, status }: { label: string; status: unknown }) {
  return (
    <Tag color={statusColor(status)}>
      {label}: {String(status ?? "UNKNOWN")}
    </Tag>
  );
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

export default function AdminOperationsDashboardPage() {
  const [refreshMs, setRefreshMs] = useState<RefreshMs>(10_000);
  const [activeTab, setActiveTab] = useState("overview");
  const pageVisible = usePageVisible();
  const interval = pageVisible && refreshMs > 0 ? refreshMs : false;

  const overviewQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardOverview(),
    queryFn: adminApi.getOpsDashboardOverview,
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const accountsQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardAccounts(),
    queryFn: () =>
      adminApi.getOpsDashboardAccounts({ include_broker_balances: true }),
    enabled: activeTab === "accounts" || activeTab === "overview",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const ordersQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardOrders({ limit: 50 }),
    queryFn: () => adminApi.getOpsDashboardOrders({ limit: 50 }),
    enabled: activeTab === "orders",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const riskQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardRisk(),
    queryFn: adminApi.getOpsDashboardRisk,
    enabled: activeTab === "risk",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const schedulersQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardSchedulers(),
    queryFn: adminApi.getOpsDashboardSchedulers,
    enabled: activeTab === "schedulers",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const runtimesQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardRuntimes(),
    queryFn: adminApi.getOpsDashboardRuntimes,
    enabled: activeTab === "schedulers",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const positionsQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardPositions(),
    queryFn: adminApi.getOpsDashboardPositions,
    enabled: activeTab === "positions",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const alertsQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardAlerts(),
    queryFn: () => adminApi.getOpsDashboardAlerts({ limit: 100 }),
    enabled: activeTab === "alerts",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const auditsQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardAudits({ limit: 50 }),
    queryFn: () => adminApi.getOpsDashboardAudits({ limit: 50 }),
    enabled: activeTab === "audit",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const notificationsQuery = useQuery({
    queryKey: queryKeys.admin.opsDashboardNotifications(),
    queryFn: () => adminApi.getOpsDashboardNotifications({ limit: 50 }),
    enabled: activeTab === "audit",
    refetchInterval: interval,
    placeholderData: (prev) => prev,
  });

  const overview = useMemo(
    () => rec(overviewQuery.data),
    [overviewQuery.data],
  );
  const checkedAt = cell(overview.checked_at);

  const refreshAll = () => {
    void overviewQuery.refetch();
    if (activeTab === "accounts") void accountsQuery.refetch();
    if (activeTab === "orders") void ordersQuery.refetch();
    if (activeTab === "risk") void riskQuery.refetch();
    if (activeTab === "schedulers") {
      void schedulersQuery.refetch();
      void runtimesQuery.refetch();
    }
    if (activeTab === "positions") void positionsQuery.refetch();
    if (activeTab === "alerts") void alertsQuery.refetch();
    if (activeTab === "audit") {
      void auditsQuery.refetch();
      void notificationsQuery.refetch();
    }
  };

  const overviewCards = useMemo(() => {
    const brokers = rec(overview.brokers);
    const sched = rec(overview.schedulers);
    const runtime = rec(overview.runtime);
    const kill = rec(overview.kill_switch);
    const alerts = rec(overview.alerts);
    const db = rec(overview.database);
    return [
      { label: L.overall, status: overview.overall_status },
      { label: L.database, status: db.status },
      { label: "Upbit", status: rec(brokers.UPBIT).status },
      { label: "Kiwoom", status: rec(brokers.KIWOOM).status },
      {
        label: L.tradingScheduler,
        status: rec(sched.trading).actual_state,
      },
      {
        label: L.trackingScheduler,
        status: rec(sched.tracking).actual_state,
      },
      {
        label: L.postFillScheduler,
        status: rec(sched.post_fill).actual_state,
      },
      {
        label: L.recoveryScheduler,
        status: rec(sched.recovery).actual_state,
      },
      {
        label: L.runtime,
        status: `run=${cell(runtime.running_count)} pause=${cell(runtime.paused_count)} err=${cell(runtime.error_count)}`,
      },
      {
        label: L.killSwitch,
        status: kill.global_active ? "ACTIVE" : "OFF",
      },
      { label: L.criticalAlerts, status: cell(alerts.critical) },
      { label: L.manualReview, status: cell(alerts.manual_review) },
    ];
  }, [overview]);

  return (
    <AdminPageShell
      title={L.pageTitle}
      description={L.pageDescription}
      extra={
        <Space wrap>
          <Typography.Text type="secondary">
            {L.lastChecked}: {checkedAt || "-"}
          </Typography.Text>
          <Select<RefreshMs>
            value={refreshMs}
            style={{ width: 140 }}
            onChange={setRefreshMs}
            options={[
              { value: 0, label: L.autoOff },
              { value: 5000, label: "5s" },
              { value: 10000, label: "10s" },
              { value: 30000, label: "30s" },
              { value: 60000, label: "60s" },
            ]}
          />
          <Button onClick={refreshAll}>{L.refresh}</Button>
          <Link href={adminRoutes.accounts}>{L.accountsLink}</Link>
          {OPERATION_CANONICAL_LINKS.filter(
            (item) => item.href !== adminRoutes.operationsDashboard,
          ).map((item) => (
            <Link key={item.id} href={item.href}>
              {item.label}
            </Link>
          ))}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title={L.readOnlyBanner}
      />

      {overviewQuery.isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          title={L.overviewFailed}
          description={toApiError(overviewQuery.error).message}
        />
      ) : null}

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: "overview",
            label: L.tabOverview,
            children: (
              <Row gutter={[12, 12]}>
                {overviewCards.map((card) => (
                  <Col xs={24} sm={12} md={8} lg={6} key={card.label}>
                    <Card size="small" title={card.label}>
                      <StatusTag label={L.status} status={card.status} />
                    </Card>
                  </Col>
                ))}
              </Row>
            ),
          },
          {
            key: "accounts",
            label: L.tabAccounts,
            children: (
              <AccountsTab
                data={accountsQuery.data}
                loading={accountsQuery.isLoading}
                error={accountsQuery.error}
              />
            ),
          },
          {
            key: "orders",
            label: L.tabOrders,
            children: (
              <OrdersTab
                data={ordersQuery.data}
                loading={ordersQuery.isLoading}
                error={ordersQuery.error}
              />
            ),
          },
          {
            key: "risk",
            label: L.tabRisk,
            children: (
              <RiskTab
                data={riskQuery.data}
                loading={riskQuery.isLoading}
                error={riskQuery.error}
              />
            ),
          },
          {
            key: "schedulers",
            label: L.tabSchedulers,
            children: (
              <Space direction="vertical" style={{ width: "100%" }} size="middle">
                <SchedulersTab
                  data={schedulersQuery.data}
                  loading={schedulersQuery.isLoading}
                />
                <RuntimesTab
                  data={runtimesQuery.data}
                  loading={runtimesQuery.isLoading}
                />
              </Space>
            ),
          },
          {
            key: "positions",
            label: L.tabPositions,
            children: (
              <PositionsTab
                data={positionsQuery.data}
                loading={positionsQuery.isLoading}
              />
            ),
          },
          {
            key: "alerts",
            label: L.tabAlerts,
            children: (
              <AlertsTab
                data={alertsQuery.data}
                loading={alertsQuery.isLoading}
              />
            ),
          },
          {
            key: "audit",
            label: L.tabAudit,
            children: (
              <Tabs
                items={[
                  {
                    key: "audits",
                    label: L.tabAuditSub,
                    children: (
                      <AuditsTab
                        data={auditsQuery.data}
                        loading={auditsQuery.isLoading}
                      />
                    ),
                  },
                  {
                    key: "notifications",
                    label: L.tabNotificationSub,
                    children: (
                      <NotificationsTab
                        data={notificationsQuery.data}
                        loading={notificationsQuery.isLoading}
                      />
                    ),
                  },
                ]}
              />
            ),
          },
        ]}
      />
    </AdminPageShell>
  );
}

function AccountsTab({
  data,
  loading,
  error,
}: {
  data: unknown;
  loading: boolean;
  error: unknown;
}) {
  if (error) {
    return <Alert type="error" title={toApiError(error).message} showIcon />;
  }
  const rows = extractRows(rec(data).accounts);
  return (
    <Table
      size="small"
      loading={loading}
      rowKey={(r) => String(rec(r).user_broker_account_id)}
      dataSource={rows}
      pagination={{ pageSize: 20 }}
      scroll={{ x: 1400 }}
      locale={{ emptyText: <Empty description={L.noAccounts} /> }}
      columns={[
        { title: "UBA", dataIndex: "user_broker_account_id", width: 70 },
        {
          title: L.owner,
          dataIndex: "owner_login_id_masked",
          render: (v) => cell(v),
        },
        { title: L.broker, dataIndex: "broker_code", width: 90 },
        {
          title: L.credential,
          dataIndex: "credential_status",
          render: (v) => <StatusTag label={L.credential} status={v} />,
        },
        {
          title: L.dryRunReady,
          dataIndex: "dry_run_ready",
          render: (v) => (
            <Tag color={v ? "success" : "error"}>{v ? "READY" : "BLOCKED"}</Tag>
          ),
        },
        {
          title: L.liveExecutionReady,
          dataIndex: "live_execution_ready",
          render: (v) => (
            <Tag color={v ? "success" : "default"}>{v ? "READY" : "NO"}</Tag>
          ),
        },
        {
          title: "LIVE/ARM",
          render: (_, r) => {
            const row = rec(r);
            return (
              <Space>
                <Tag color={row.live_order_enabled ? "error" : "default"}>
                  LIVE {row.live_order_enabled ? "ON" : "OFF"}
                </Tag>
                <Tag color={row.live_armed ? "warning" : "default"}>
                  ARM {row.live_armed ? "ON" : "OFF"}
                </Tag>
              </Space>
            );
          },
        },
        {
          title: `${L.orderableKrw}/${L.lockedKrw}`,
          render: (_, r) => {
            const row = rec(r);
            return `${cell(row.orderable_krw)} / ${cell(row.locked_krw)} (${cell(row.balance_status)})`;
          },
        },
        {
          title: L.dailyLoss,
          render: (_, r) => {
            const row = rec(r);
            return `${cell(row.current_daily_loss)} / ${cell(row.max_daily_loss_limit)}`;
          },
        },
        {
          title: L.blockers,
          dataIndex: "blockers",
          render: (v) => {
            const list = Array.isArray(v) ? v.map(String) : [];
            if (!list.length) return "-";
            return (
              <Collapse
                size="small"
                items={[
                  {
                    key: "b",
                    label: `${list.length} items`,
                    children: (
                      <ul style={{ margin: 0, paddingLeft: 16 }}>
                        {list.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    ),
                  },
                ]}
              />
            );
          },
        },
      ]}
    />
  );
}

function OrdersTab({
  data,
  loading,
  error,
}: {
  data: unknown;
  loading: boolean;
  error: unknown;
}) {
  if (error) {
    return <Alert type="error" title={toApiError(error).message} showIcon />;
  }
  const rows = extractRows(rec(data).orders);
  return (
    <Table
      size="small"
      loading={loading}
      rowKey={(r) => String(rec(r).order_id)}
      dataSource={rows}
      scroll={{ x: 1200 }}
      columns={[
        { title: "Time", dataIndex: "created_at", width: 170 },
        { title: "UBA", dataIndex: "user_broker_account_id", width: 70 },
        { title: "Broker", dataIndex: "broker_code", width: 90 },
        { title: "Market", dataIndex: "market" },
        { title: "Side", dataIndex: "side", width: 70 },
        { title: "Limit", dataIndex: "requested_price" },
        {
          title: "Internal",
          dataIndex: "internal_status",
          render: (v) => {
            const s = String(v ?? "");
            const danger = [
              "UNKNOWN",
              "SUBMISSION_UNKNOWN",
              "CANCEL_PENDING",
              "FAILED",
            ].includes(s);
            return (
              <Tag color={danger ? "error" : statusColor(s)}>{s || "-"}</Tag>
            );
          },
        },
        { title: "Broker Status", dataIndex: "broker_status" },
        { title: "Filled Qty", dataIndex: "filled_quantity" },
        { title: "Avg Price", dataIndex: "average_fill_price" },
        { title: "Remaining", dataIndex: "remaining_quantity" },
        { title: "Post-fill", dataIndex: "post_fill_status" },
        {
          title: "Manual",
          dataIndex: "manual_review_required",
          render: (v) => (v ? <Tag color="error">YES</Tag> : "NO"),
        },
      ]}
    />
  );
}

function RiskTab({
  data,
  loading,
  error,
}: {
  data: unknown;
  loading: boolean;
  error: unknown;
}) {
  if (error) {
    return <Alert type="error" title={toApiError(error).message} showIcon />;
  }
  const rows = extractRows(rec(data).accounts);
  return (
    <Table
      size="small"
      loading={loading}
      rowKey={(r) => String(rec(r).user_broker_account_id)}
      dataSource={rows}
      columns={[
        { title: "UBA", dataIndex: "user_broker_account_id", width: 70 },
        { title: L.broker, dataIndex: "broker_code" },
        { title: "Daily PnL", dataIndex: "current_daily_pnl" },
        { title: L.dailyLoss, dataIndex: "current_daily_loss" },
        { title: "Limit", dataIndex: "max_daily_loss_limit" },
        {
          title: L.remainingCapacity,
          dataIndex: "remaining_daily_loss_capacity",
        },
        {
          title: "Risk Status",
          dataIndex: "risk_status",
          render: (v) => <StatusTag label="Risk" status={v} />,
        },
        { title: "Max Order", dataIndex: "max_order_amount" },
        { title: "Open", dataIndex: "current_open_orders" },
        { title: "Today", dataIndex: "today_orders" },
        {
          title: "Kill",
          dataIndex: "kill_switch_active",
          render: (v) => (
            <Tag color={v ? "error" : "success"}>{v ? "ACTIVE" : "OFF"}</Tag>
          ),
        },
      ]}
    />
  );
}

function SchedulersTab({
  data,
  loading,
}: {
  data: unknown;
  loading: boolean;
}) {
  const rows = extractRows(rec(data).schedulers);
  return (
    <Card size="small" title={L.tabSchedulers}>
      <Table
        size="small"
        loading={loading}
        rowKey={(r) => String(rec(r).scheduler_name)}
        dataSource={rows}
        pagination={false}
        columns={[
          { title: "Name", dataIndex: "scheduler_name" },
          { title: "Scope", dataIndex: "scope" },
          { title: "Desired", dataIndex: "desired_state" },
          {
            title: "Actual",
            dataIndex: "actual_state",
            render: (v) => <StatusTag label="Actual" status={v} />,
          },
          {
            title: "Running",
            dataIndex: "running",
            render: (v) => String(v),
          },
          { title: "Failures", dataIndex: "consecutive_failures" },
          {
            title: "Stale",
            dataIndex: "stale",
            render: (v) => (v ? <Tag color="warning">STALE</Tag> : "-"),
          },
        ]}
      />
    </Card>
  );
}

function RuntimesTab({
  data,
  loading,
}: {
  data: unknown;
  loading: boolean;
}) {
  const rows = extractRows(rec(data).runtimes);
  return (
    <Card size="small" title={L.runtime}>
      <Table
        size="small"
        loading={loading}
        rowKey={(r) =>
          [
            cell(rec(r).scope),
            cell(rec(r).account_id),
            cell(rec(r).strategy_id),
            cell(rec(r).broker_code),
          ].join("-")
        }
        dataSource={rows}
        locale={{ emptyText: <Empty description="No runtimes" /> }}
        columns={[
          { title: "Scope", dataIndex: "scope" },
          { title: "UBA", dataIndex: "account_id" },
          { title: "Broker", dataIndex: "broker_code" },
          { title: "Strategy", dataIndex: "strategy_id" },
          {
            title: "State",
            dataIndex: "state",
            render: (v) => <StatusTag label="State" status={v} />,
          },
          { title: "Heartbeat", dataIndex: "last_heartbeat_at" },
          { title: "Last Error", dataIndex: "last_error_code" },
          {
            title: "Stale",
            dataIndex: "stale",
            render: (v) => (v ? <Tag color="warning">STALE</Tag> : "-"),
          },
        ]}
      />
    </Card>
  );
}

function PositionsTab({
  data,
  loading,
}: {
  data: unknown;
  loading: boolean;
}) {
  const rows = extractRows(rec(data).positions);
  return (
    <Table
      size="small"
      loading={loading}
      rowKey={(r) =>
        [
          cell(rec(r).user_broker_account_id),
          cell(rec(r).symbol),
          cell(rec(r).snapshot_time),
        ].join("-")
      }
      dataSource={rows}
      columns={[
        { title: "UBA", dataIndex: "user_broker_account_id", width: 70 },
        { title: "Broker", dataIndex: "broker_code" },
        { title: "Market", dataIndex: "market" },
        { title: "Qty", dataIndex: "quantity" },
        { title: "Avg", dataIndex: "average_price" },
        { title: "Mark", dataIndex: "current_price" },
        { title: "Eval", dataIndex: "evaluation_amount" },
        { title: "uPnL", dataIndex: "unrealized_pnl" },
        { title: "Return", dataIndex: "return_rate" },
        { title: "Snapshot", dataIndex: "snapshot_time" },
        {
          title: "Stale",
          dataIndex: "stale",
          render: (v) => (v ? <Tag color="warning">STALE</Tag> : "-"),
        },
      ]}
    />
  );
}

function AlertsTab({
  data,
  loading,
}: {
  data: unknown;
  loading: boolean;
}) {
  const rows = extractRows(rec(data).alerts);
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <Link href={adminRoutes.recovery}>Open Recovery</Link>
      <Table
        size="small"
        loading={loading}
        rowKey={(r) =>
          [
            cell(rec(r).code),
            cell(rec(r).created_at),
            cell(rec(r).user_broker_account_id),
            cell(rec(r).title),
          ].join("|")
        }
        dataSource={rows}
        columns={[
          { title: "Time", dataIndex: "created_at", width: 170 },
          {
            title: "Severity",
            dataIndex: "severity",
            render: (v) => <StatusTag label="Sev" status={v} />,
          },
          { title: "Category", dataIndex: "category" },
          { title: "Code", dataIndex: "code" },
          { title: "UBA", dataIndex: "user_broker_account_id" },
          { title: "Title", dataIndex: "title" },
          { title: "Message", dataIndex: "message" },
          {
            title: "Manual",
            dataIndex: "manual_review_required",
            render: (v) => (v ? <Tag color="error">YES</Tag> : "NO"),
          },
        ]}
      />
    </Space>
  );
}

function AuditsTab({
  data,
  loading,
}: {
  data: unknown;
  loading: boolean;
}) {
  const rows = extractRows(rec(data).audits);
  return (
    <Table
      size="small"
      loading={loading}
      rowKey={(r) =>
        [
          cell(rec(r).occurred_at),
          cell(rec(r).event_type),
          cell(rec(r).actor),
          cell(rec(r).correlation_id),
          cell(rec(r).target_id),
        ].join("|")
      }
      dataSource={rows}
      columns={[
        { title: "Time", dataIndex: "occurred_at" },
        { title: "Event", dataIndex: "event_type" },
        { title: "Actor", dataIndex: "actor" },
        { title: "Target", dataIndex: "target_id" },
        { title: "Result", dataIndex: "result" },
        { title: "Correlation", dataIndex: "correlation_id" },
        { title: "Summary", dataIndex: "summary" },
      ]}
    />
  );
}

function NotificationsTab({
  data,
  loading,
}: {
  data: unknown;
  loading: boolean;
}) {
  const root = rec(data);
  const rows = extractRows(root.notifications);
  const telegram = rec(root.telegram);
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      <StatusTag label="Telegram" status={telegram.status} />
      <Table
        size="small"
        loading={loading}
        rowKey={(r) =>
          [
            cell(rec(r).created_at),
            cell(rec(r).channel),
            cell(rec(r).event_type),
            cell(rec(r).title),
          ].join("|")
        }
        dataSource={rows}
        columns={[
          { title: "Time", dataIndex: "created_at" },
          { title: "Channel", dataIndex: "channel" },
          { title: "Severity", dataIndex: "severity" },
          { title: "Event", dataIndex: "event_type" },
          { title: "Title", dataIndex: "title" },
          { title: "Delivery", dataIndex: "delivery_status" },
          { title: "Preview", dataIndex: "message_preview" },
        ]}
      />
    </Space>
  );
}
