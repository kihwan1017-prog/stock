"use client";

/**
 * 시스템·인프라 상세 — 운영 탭 Accordion 내부 (기본 접힘).
 */

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

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";

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

type Props = {
  data: Record<string, unknown>;
  loading?: boolean;
};

export function DashboardSystemInfra({ data, loading }: Props) {
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

  const tradingSched = rec(runtime.scheduler);
  const strategyRt = rec(runtime.strategy_runtime);
  const recovery = rec(runtime.recovery);
  const live = rec(safety.live);
  const arm = rec(safety.arm);
  const kill = rec(safety.kill_switch);

  const brokerRows = Object.entries(broker).map(([code, row]) => ({
    broker: code,
    ...rec(row),
  }));
  const positionRows = extractRows(positions.items);
  const auditRows = extractRows(audit.items);
  const accountRows = extractRows(accounts.items);
  const schedulerRows = extractRows(scheduler.items);
  const aiProviderRows = extractRows(aiProviders.items);

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card title="System" size="small" loading={loading}>
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}>
            <Statistic title="API" value={cell(system.api_status)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic title="DB" value={cell(rec(system.database).status)} />
          </Col>
          <Col xs={12} md={6}>
            <Statistic
              title="Migration"
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
      </Card>

      <Card title="Trading Engine" size="small">
        <Space wrap>
          <Tag color={healthColor(tradingSched.desired_state)}>
            Scheduler desired: {cell(tradingSched.desired_state)}
          </Tag>
          <Tag color={healthColor(strategyRt.state)}>
            Runtime: {cell(strategyRt.state)}
          </Tag>
          <Tag color={healthColor(recovery.actual_state)}>
            Recovery: {cell(recovery.actual_state)}
          </Tag>
        </Space>
      </Card>

      <Card title="Trading Safety" size="small">
        <Space wrap>
          <Tag color={healthColor(live.status)}>LIVE: {cell(live.status)}</Tag>
          <Tag color={healthColor(arm.status)}>ARM: {cell(arm.status)}</Tag>
          <Tag color={kill.active ? "error" : "success"}>
            Kill: {kill.active ? "ACTIVE" : "OFF"}
          </Tag>
        </Space>
      </Card>

      <Card title="Broker" size="small">
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
              render: (v) => <Tag color={healthColor(v)}>{cell(v)}</Tag>,
            },
            { title: "Accounts", dataIndex: "account_count" },
          ]}
        />
      </Card>

      <Card title="Orders (오늘)" size="small">
        <Typography.Text>
          Submitted {cell(orders.submitted)} · Filled {cell(orders.filled)}
        </Typography.Text>
      </Card>

      <Card title="Accounts / Positions" size="small">
        <Table
          size="small"
          pagination={{ pageSize: 5, hideOnSinglePage: true }}
          rowKey={(r) => String(r.user_broker_account_id)}
          dataSource={accountRows}
          columns={[
            { title: "UBA", dataIndex: "user_broker_account_id" },
            { title: "Broker", dataIndex: "broker_code" },
          ]}
        />
        <Table
          size="small"
          style={{ marginTop: 12 }}
          pagination={{ pageSize: 5, hideOnSinglePage: true }}
          rowKey={(r) => String(r.symbol)}
          dataSource={positionRows}
          columns={[
            { title: "Symbol", dataIndex: "symbol" },
            { title: "PnL", dataIndex: "unrealized_pnl" },
          ]}
        />
      </Card>

      <Card title="Scheduler" size="small">
        <Table
          size="small"
          pagination={false}
          rowKey="scheduler_name"
          dataSource={schedulerRows}
          columns={[
            { title: "Name", dataIndex: "scheduler_name" },
            { title: "Actual", dataIndex: "actual_state" },
          ]}
        />
      </Card>

      <Card title="AI Providers" size="small">
        <Table
          size="small"
          pagination={false}
          rowKey="id"
          dataSource={aiProviderRows}
          columns={[
            { title: "Provider", dataIndex: "id" },
            { title: "Status", dataIndex: "status" },
          ]}
        />
      </Card>

      <Card title="Audit" size="small">
        <Table
          size="small"
          pagination={{ pageSize: 5 }}
          rowKey={(r) => String(r.occurred_at)}
          dataSource={auditRows}
          columns={[
            { title: "Time", dataIndex: "occurred_at", render: cell },
            { title: "Event", dataIndex: "event_type" },
          ]}
        />
      </Card>
    </Space>
  );
}
