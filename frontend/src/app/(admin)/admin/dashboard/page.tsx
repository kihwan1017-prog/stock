"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Card,
  Col,
  Descriptions,
  Flex,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
} from "antd";

import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function StatusTag({
  status,
  label,
}: {
  status: string | null | undefined;
  label: string;
}) {
  const normalized = (status ?? "").toUpperCase();
  const ok = ["UP", "OK", "CONFIGURED", "INACTIVE", "ENABLED"].includes(
    normalized,
  );
  const warn = ["DISABLED", "STOPPED", "SKIPPED", "DEGRADED", "UNKNOWN"].includes(
    normalized,
  );
  const bad = ["DOWN", "ERROR", "FAILED", "ACTIVE"].includes(normalized) &&
    label.toLowerCase().includes("kill");
  // Kill Switch ACTIVE = bad; other ACTIVE = ok for strategies elsewhere
  let color: "success" | "error" | "warning" | "default" = "default";
  if (label === "Kill Switch") {
    color = normalized === "ACTIVE" ? "error" : normalized ? "success" : "default";
  } else if (ok) {
    color = "success";
  } else if (warn) {
    color = "warning";
  } else if (normalized === "DOWN" || normalized === "FAILED") {
    color = "error";
  } else if (bad) {
    color = "error";
  }
  return (
    <Tag color={color}>
      {label}: {normalized || "…"}
    </Tag>
  );
}

function formatNumber(value: unknown, suffix = ""): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const num = Number(value);
  if (Number.isFinite(num)) {
    return `${num.toLocaleString("ko-KR")}${suffix}`;
  }
  return `${cell(value)}${suffix}`;
}

function formatPct(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const num = Number(value);
  if (Number.isFinite(num)) {
    return `${num.toFixed(4)}%`;
  }
  return cell(value);
}

export default function AdminDashboardPage() {
  const summaryQuery = useQuery({
    queryKey: queryKeys.dashboard.summary("1"),
    queryFn: () =>
      adminApi.getDashboardSummary({
        account_id: 1,
        market_code: "KRX",
        mode_code: "PAPER",
        recent_limit: 10,
      }),
    refetchInterval: 30_000,
  });

  const data = asRecord(summaryQuery.data);
  const kpis = asRecord(data?.kpis);
  const kill = asRecord(data?.kill_switch);
  const scheduler = asRecord(data?.scheduler);
  const broker = asRecord(data?.broker);
  const risk = asRecord(data?.risk);
  const ollama = asRecord(data?.ollama);
  const database = asRecord(data?.database);
  const strategies = extractRows(data?.active_strategies);
  const recentErrors = extractRows(data?.recent_errors);
  const recentLogs = extractRows(data?.recent_logs);
  const recentJobs = extractRows(data?.recent_jobs);

  const error = summaryQuery.error
    ? toApiError(summaryQuery.error)
    : null;
  const todayPnl = Number(kpis?.today_pnl ?? NaN);
  const unrealized = Number(kpis?.unrealized_pnl ?? NaN);
  const realized = Number(kpis?.realized_pnl ?? NaN);

  return (
    <AdminPageShell
      title="Dashboard"
      description="운영 Summary — /api/v1/dashboard/admin-summary"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        {error ? (
          <Typography.Text type="danger">{error.message}</Typography.Text>
        ) : null}

        <Space wrap>
          <StatusTag status={cell(database?.status)} label="DB" />
          <StatusTag status={cell(ollama?.status)} label="Ollama" />
          <StatusTag status={cell(broker?.status)} label="Broker" />
          <StatusTag status={cell(scheduler?.status)} label="Scheduler" />
          <StatusTag
            status={cell(kill?.status)}
            label="Kill Switch"
          />
          <Tag>
            Health: {cell(data?.health_status ?? "…")}
          </Tag>
          <Tag>
            평가: {cell(kpis?.valuation_mode ?? "…")}
          </Tag>
        </Space>

        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={summaryQuery.isLoading}>
              <Statistic
                title="총 자산"
                value={formatNumber(kpis?.total_equity)}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={summaryQuery.isLoading}>
              <Statistic
                title="오늘 수익률"
                value={formatPct(kpis?.today_return_rate)}
                styles={{
                  content: {
                    color:
                      Number.isFinite(todayPnl) && todayPnl < 0
                        ? "#cf1322"
                        : Number.isFinite(todayPnl) && todayPnl > 0
                          ? "#3f8600"
                          : undefined,
                  },
                }}
              />
              <Typography.Text type="secondary">
                오늘 PnL {formatNumber(kpis?.today_pnl)}
              </Typography.Text>
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={summaryQuery.isLoading}>
              <Statistic
                title="평가손익"
                value={formatNumber(kpis?.unrealized_pnl)}
                styles={{
                  content: {
                    color:
                      Number.isFinite(unrealized) && unrealized < 0
                        ? "#cf1322"
                        : Number.isFinite(unrealized) && unrealized > 0
                          ? "#3f8600"
                          : undefined,
                  },
                }}
              />
            </Card>
          </Col>
          <Col xs={24} sm={12} lg={6}>
            <Card size="small" loading={summaryQuery.isLoading}>
              <Statistic
                title="실현손익"
                value={formatNumber(kpis?.realized_pnl)}
                styles={{
                  content: {
                    color:
                      Number.isFinite(realized) && realized < 0
                        ? "#cf1322"
                        : Number.isFinite(realized) && realized > 0
                          ? "#3f8600"
                          : undefined,
                  },
                }}
              />
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={12}>
            <Card
              title={`실행 전략 (${strategies.length})`}
              size="small"
              loading={summaryQuery.isLoading}
            >
              <Table
                size="small"
                pagination={false}
                rowKey={(row) =>
                  String(row.strategy_deployment_id ?? row.strategy_code)
                }
                dataSource={strategies}
                locale={{ emptyText: "ACTIVE 전략 없음" }}
                columns={[
                  { title: "전략", dataIndex: "strategy_code" },
                  { title: "심볼", dataIndex: "symbol", render: (v) => v ?? "—" },
                  { title: "모드", dataIndex: "mode_code" },
                  {
                    title: "상태",
                    dataIndex: "status_code",
                    render: (v) => <Tag color="success">{cell(v)}</Tag>,
                  },
                ]}
              />
            </Card>
          </Col>
          <Col xs={24} lg={12}>
            <Card title="운영 상태" size="small" loading={summaryQuery.isLoading}>
              <Descriptions column={1} size="small">
                <Descriptions.Item label="Scheduler">
                  {cell(scheduler?.status)} · jobs {cell(scheduler?.job_count)}
                </Descriptions.Item>
                <Descriptions.Item label="Broker">
                  {cell(broker?.provider)} · {cell(broker?.status)}
                  {broker?.use_mock ? " (mock)" : ""}
                </Descriptions.Item>
                <Descriptions.Item label="Risk / Kill Switch">
                  {kill?.active === true ? (
                    <Tag color="error">ACTIVE</Tag>
                  ) : (
                    <Tag color="success">INACTIVE</Tag>
                  )}
                  {kill?.reason ? ` · ${cell(kill.reason)}` : ""}
                </Descriptions.Item>
                <Descriptions.Item label="Ollama">
                  {cell(ollama?.status)}
                  {ollama?.model_count != null
                    ? ` · models ${cell(ollama.model_count)}`
                    : ""}
                </Descriptions.Item>
                <Descriptions.Item label="DB">
                  {cell(database?.status)}
                </Descriptions.Item>
                <Descriptions.Item label="Live Order">
                  {risk?.live_order_enabled === true ? "ENABLED" : "DISABLED"}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={24} lg={8}>
            <Card title="최근 오류" size="small" loading={summaryQuery.isLoading}>
              {recentErrors.length === 0 ? (
                <Typography.Text type="secondary">최근 오류 없음</Typography.Text>
              ) : (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {recentErrors.slice(0, 10).map((row, index) => (
                    <Typography.Text
                      key={index}
                      type="danger"
                      style={{ fontSize: 12, display: "block" }}
                    >
                      [{cell(row.source)}]{" "}
                      {cell(row.error_message ?? row.message ?? row)}
                    </Typography.Text>
                  ))}
                </Space>
              )}
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card title="최근 로그 (Audit)" size="small" loading={summaryQuery.isLoading}>
              {recentLogs.length === 0 ? (
                <Typography.Text type="secondary">감사 로그 없음</Typography.Text>
              ) : (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {recentLogs.slice(0, 10).map((row, index) => (
                    <Space key={index} orientation="vertical" size={0}>
                      <Typography.Text strong style={{ fontSize: 12 }}>
                        {cell(row.event_type)}
                      </Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                        {cell(row.actor)} · {cell(row.created_at)}
                      </Typography.Text>
                    </Space>
                  ))}
                </Space>
              )}
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card title="최근 작업 (Jobs)" size="small" loading={summaryQuery.isLoading}>
              {recentJobs.length === 0 ? (
                <Typography.Text type="secondary">작업 이력 없음</Typography.Text>
              ) : (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {recentJobs.slice(0, 10).map((row, index) => (
                    <Flex
                      key={index}
                      justify="space-between"
                      align="center"
                      gap={8}
                    >
                      <Typography.Text style={{ fontSize: 12 }}>
                        {cell(row.job_name)}
                      </Typography.Text>
                      <Tag
                        color={
                          String(row.status_code).toUpperCase() === "FAILED"
                            ? "error"
                            : String(row.status_code).toUpperCase() === "SUCCESS"
                              ? "success"
                              : "processing"
                        }
                      >
                        {cell(row.status_code)}
                      </Tag>
                    </Flex>
                  ))}
                </Space>
              )}
            </Card>
          </Col>
        </Row>
      </Space>
    </AdminPageShell>
  );
}
