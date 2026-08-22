"use client";

/**
 * STEP 10-3 — Operations Center (Read-only, 5s polling).
 * Mutation / 주문 / LIVE / ARM / Scheduler 제어 없음.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { queryKeys } from "@/lib/query/queryKeys";

import { TradingCockpitPanel } from "./TradingCockpitPanel";

function rec(value: unknown): Record<string, unknown> {
  return asRecord(value) ?? {};
}

function healthColor(health: unknown): string {
  const h = String(health ?? "UNKNOWN").toUpperCase();
  if (["HEALTHY", "OK", "RUNNING", "CONNECTED", "OFF"].includes(h)) {
    return "success";
  }
  if (["WARNING", "DEGRADED", "PAUSED", "STALE", "ON"].includes(h)) {
    return "warning";
  }
  if (["ERROR", "CRITICAL", "FAILED", "BLOCKED", "OFFLINE"].includes(h)) {
    return "error";
  }
  return "default";
}

function HealthBadge({
  label,
  health,
  detail,
}: {
  label: string;
  health: unknown;
  detail?: string;
}) {
  return (
    <Tag color={healthColor(health)}>
      {label}: {detail ?? String(health ?? "—")}
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

type Props = {
  refreshMs?: number;
};

export function OperationsCenterDashboard({ refreshMs = 5000 }: Props) {
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
  const runtime = rec(data.runtime);
  const scheduler = rec(data.scheduler);
  const safety = rec(data.safety);
  const broker = rec(data.broker);
  const orders = rec(data.orders);
  const accounts = rec(data.accounts);
  const positions = rec(data.positions);
  const audit = rec(data.audit);
  const aiProviders = rec(data.ai_providers);
  const aiPromptMeta = rec(data.ai_prompt_meta);

  const tradingSched = rec(runtime.scheduler);
  const strategyRt = rec(runtime.strategy_runtime);
  const recovery = rec(runtime.recovery);
  const live = rec(safety.live);
  const arm = rec(safety.arm);
  const kill = rec(safety.kill_switch);

  const brokerRows = useMemo(() => {
    return Object.entries(broker).map(([code, row]) => ({
      broker: code,
      ...rec(row),
    }));
  }, [broker]);

  const positionRows = extractRows(positions.items);
  const auditRows = extractRows(audit.items);
  const accountRows = extractRows(accounts.items);
  const schedulerRows = extractRows(scheduler.items);
  const aiProviderRows = extractRows(aiProviders.items);

  const lastRefresh = data.checked_at
    ? new Date(String(data.checked_at)).toLocaleString("ko-KR")
    : "—";

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
        <Space wrap>
          <HealthBadge
            label="Overall"
            health={system.health}
          />
          <Tag>Read-only</Tag>
          <Typography.Text type="secondary">
            마지막 갱신: {lastRefresh}
            {summaryQuery.isFetching ? " (갱신 중…)" : ""}
          </Typography.Text>
        </Space>
      </Space>

      <TradingCockpitPanel
        refreshMs={typeof interval === "number" ? interval : 0}
        systemHealth={system.health}
        killActive={Boolean(kill.active)}
        criticalConflict={Number(safety.pending_conflict ?? 0)}
      />

      {/* ① System */}
      <Card title="① System" size="small" loading={summaryQuery.isLoading}>
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <Statistic title="API" value={cell(system.api_status)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="DB" value={cell(rec(system.database).status)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="Migration Head"
              value={system.migration_head ? "OK" : "STALE"}
            />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="Uptime (s)"
              value={Number(system.uptime_seconds ?? 0)}
            />
          </Col>
        </Row>
        <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }} style={{ marginTop: 12 }}>
          <Descriptions.Item label="Version">
            {cell(system.backend_version)} / {cell(system.build_version)}
          </Descriptions.Item>
          <Descriptions.Item label="Git">
            {cell(system.git_commit)}
          </Descriptions.Item>
          <Descriptions.Item label="Server Time">
            {cell(system.server_time)}
          </Descriptions.Item>
          <Descriptions.Item label="Timezone">
            {cell(system.timezone)}
          </Descriptions.Item>
          <Descriptions.Item label="Outbox Queue">
            {cell(system.outbox_queue)}
          </Descriptions.Item>
          <Descriptions.Item label="Event Queue">
            {cell(system.event_queue)}
          </Descriptions.Item>
          <Descriptions.Item label="CPU">
            {cell(rec(system.cpu).percent ?? rec(system.cpu).logical_count)}
          </Descriptions.Item>
          <Descriptions.Item label="Memory %">
            {cell(rec(system.memory).used_percent)}
          </Descriptions.Item>
          <Descriptions.Item label="Disk %">
            {cell(rec(system.disk).used_percent)}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* ② Trading Engine */}
      <Card title="② Trading Engine" size="small">
        <Space wrap>
          <HealthBadge
            label="Scheduler desired"
            health={tradingSched.desired_state}
          />
          <HealthBadge
            label="Scheduler actual"
            health={tradingSched.actual_state}
          />
          <HealthBadge label="Health" health={tradingSched.health} />
          {tradingSched.blocked_reason ? (
            <Tag color="warning">
              blocked: {cell(tradingSched.blocked_reason)}
            </Tag>
          ) : null}
          <HealthBadge
            label="Strategy Runtime"
            health={strategyRt.state}
            detail={String(strategyRt.running_count ?? 0)}
          />
          <HealthBadge
            label="Recovery"
            health={recovery.actual_state}
          />
        </Space>
        <Descriptions size="small" column={2} style={{ marginTop: 12 }}>
          <Descriptions.Item label="Heartbeat">
            {cell(rec(tradingSched.heartbeat).last_heartbeat_at)}
          </Descriptions.Item>
          <Descriptions.Item label="Persisted">
            {tradingSched.persisted ? "yes" : "no"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* ③ Trading Safety */}
      <Card title="③ Trading Safety" size="small">
        <Space wrap>
          <HealthBadge label="LIVE" health={live.status} />
          <HealthBadge label="ARM" health={arm.status} />
          <HealthBadge
            label="Kill Switch"
            health={kill.active ? "ACTIVE" : "INACTIVE"}
          />
          <Tag>Submission Unknown: {cell(safety.submission_unknown)}</Tag>
          <Tag>Pending Conflict: {cell(safety.pending_conflict)}</Tag>
          <Tag>Account Pause: {cell(safety.account_pause_count)}</Tag>
        </Space>
      </Card>

      {/* ④ Broker */}
      <Card title="④ Broker" size="small">
        <Table
          size="small"
          pagination={false}
          rowKey="broker"
          dataSource={brokerRows}
          columns={[
            { title: "Broker", dataIndex: "broker" },
            {
              title: "Health",
              dataIndex: "health",
              render: (v) => (
                <Tag color={healthColor(v)}>{cell(v)}</Tag>
              ),
            },
            {
              title: "Connected",
              dataIndex: "connected",
              render: (v) => (v ? "Yes" : "No"),
            },
            { title: "Accounts", dataIndex: "account_count" },
          ]}
        />
      </Card>

      {/* ⑤ Orders */}
      <Card title="⑤ Orders (오늘)" size="small">
        <Row gutter={16}>
          <Col xs={8} md={4}>
            <Statistic title="Submitted" value={Number(orders.submitted ?? 0)} />
          </Col>
          <Col xs={8} md={4}>
            <Statistic title="Filled" value={Number(orders.filled ?? 0)} />
          </Col>
          <Col xs={8} md={4}>
            <Statistic title="Partial" value={Number(orders.partial ?? 0)} />
          </Col>
          <Col xs={8} md={4}>
            <Statistic title="Cancelled" value={Number(orders.cancelled ?? 0)} />
          </Col>
          <Col xs={8} md={4}>
            <Statistic title="Rejected" value={Number(orders.rejected ?? 0)} />
          </Col>
          <Col xs={8} md={4}>
            <Statistic
              title="거래금액"
              value={cell(orders.trade_amount)}
            />
          </Col>
        </Row>
      </Card>

      {/* ⑥ Account + ⑦ Positions */}
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="⑥ Account" size="small">
            <Statistic
              title="계좌 수"
              value={Number(accounts.count ?? 0)}
            />
            <Table
              size="small"
              pagination={{ pageSize: 5, hideOnSinglePage: true }}
              rowKey={(r) => String(r.user_broker_account_id)}
              dataSource={accountRows}
              columns={[
                { title: "UBA", dataIndex: "user_broker_account_id", width: 70 },
                { title: "Broker", dataIndex: "broker_code" },
                { title: "Status", dataIndex: "status" },
              ]}
            />
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="⑦ Positions" size="small">
            <Table
              size="small"
              pagination={{ pageSize: 8, hideOnSinglePage: true }}
              rowKey={(r) =>
                [
                  r.symbol,
                  r.quantity,
                  r.average_price,
                  r.user_broker_account_id,
                ]
                  .map((v) => String(v ?? ""))
                  .join("-")
              }
              dataSource={positionRows}
              columns={[
                { title: "Symbol", dataIndex: "symbol" },
                { title: "Qty", dataIndex: "quantity" },
                { title: "Avg", dataIndex: "average_price" },
                { title: "PnL", dataIndex: "unrealized_pnl" },
              ]}
            />
          </Card>
        </Col>
      </Row>

      {/* ⑧ Scheduler */}
      <Card title="⑧ Scheduler" size="small">
        <Table
          size="small"
          pagination={false}
          rowKey="scheduler_name"
          dataSource={schedulerRows}
          columns={[
            { title: "Name", dataIndex: "scheduler_name" },
            { title: "Desired", dataIndex: "desired_state" },
            { title: "Actual", dataIndex: "actual_state" },
            { title: "Next Run", dataIndex: "next_run_at", render: cell },
            {
              title: "Failures",
              dataIndex: "consecutive_failures",
              render: (v) => (v ? <Tag color="error">{v}</Tag> : "0"),
            },
          ]}
        />
      </Card>

      {/* ⑩ AI Providers (STEP 11-1) */}
      <Card
        title="⑩ AI Providers"
        size="small"
        extra={
          <Space>
            <HealthBadge label="Health" health={aiProviders.health} />
            <Tag>Default: {cell(aiProviders.default_provider)}</Tag>
            <Tag>Source: {cell(aiProviders.configuration_source)}</Tag>
            <Tag>Prompts A/D: {cell(aiPromptMeta.active_prompt_count)}/{cell(aiPromptMeta.draft_prompt_count)}</Tag>
            <Tag>Policies: {cell(aiPromptMeta.active_policy_count)}</Tag>
            <Tag>Schemas: {cell(aiPromptMeta.active_schema_count)}</Tag>
            <Tag>Exec Run: {cell(asRecord(data.ai_executions)?.running)}</Tag>
            <Tag>Exec Today: {cell(asRecord(data.ai_executions)?.today_requests)}</Tag>
          </Space>
        }
      >
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={aiProviderRows}
          columns={[
            { title: "Provider", dataIndex: "id", width: 140 },
            {
              title: "Status",
              dataIndex: "status",
              render: (v) => <Tag color={healthColor(v)}>{cell(v)}</Tag>,
            },
            {
              title: "Enabled",
              dataIndex: "enabled",
              width: 80,
              render: (v) => (v ? "Y" : "N"),
            },
            {
              title: "Configured",
              dataIndex: "configured",
              width: 90,
              render: (v) => (v ? "Y" : "N"),
            },
            { title: "Model", dataIndex: "model", render: cell },
            { title: "Endpoint", dataIndex: "endpoint", render: cell, ellipsis: true },
            { title: "Version", dataIndex: "version", render: cell },
            {
              title: "Latency(ms)",
              dataIndex: "latency_ms",
              render: cell,
              width: 100,
            },
            {
              title: "Circuit",
              dataIndex: "circuit_state",
              width: 100,
              render: cell,
            },
            {
              title: "Requests",
              dataIndex: "request_count",
              width: 90,
              render: cell,
            },
            {
              title: "Source",
              dataIndex: "configuration_source",
              width: 90,
              render: cell,
            },
            {
              title: "Credential",
              dataIndex: "credential_status",
              width: 100,
              render: cell,
            },
            {
              title: "Drift",
              dataIndex: "config_drift",
              width: 70,
              render: (v) => (v ? <Tag color="warning">Y</Tag> : "N"),
            },
            {
              title: "Reload?",
              dataIndex: "reload_required",
              width: 80,
              render: (v) => (v ? "Y" : "N"),
            },
            {
              title: "DB Ver",
              dataIndex: "db_config_version",
              width: 70,
              render: cell,
            },
            {
              title: "Runtime Ver",
              dataIndex: "runtime_config_version",
              width: 90,
              render: cell,
            },
            {
              title: "Capabilities",
              dataIndex: "capabilities",
              render: (caps) =>
                Array.isArray(caps) ? caps.join(", ") : cell(caps),
              ellipsis: true,
            },
          ]}
        />
      </Card>

      {/* ⑨ Audit */}
      <Card title="⑨ Audit (최근 100건)" size="small">
        <Table
          size="small"
          pagination={{ pageSize: 10 }}
          rowKey={(r) =>
            [
              r.event_type,
              r.occurred_at,
              r.actor,
              r.summary,
              r.correlation_id,
            ]
              .map((v) => String(v ?? ""))
              .join("|")
          }
          dataSource={auditRows}
          columns={[
            { title: "Time", dataIndex: "occurred_at", width: 180, render: cell },
            { title: "Event", dataIndex: "event_type" },
            { title: "Actor", dataIndex: "actor" },
            { title: "Summary", dataIndex: "summary", ellipsis: true },
          ]}
        />
      </Card>
    </Space>
  );
}
