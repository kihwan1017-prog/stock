"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Row,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo } from "react";

import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { userRoutes } from "@/config/routes";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import * as userApi from "@/features/user/api/userApi";
import { isRunnerOn } from "@/features/user/auto-trading/runnerStatus";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

const DEFAULT_EXCHANGE = "KRX";

const SESSION_PHASES = [
  "PRE_MARKET",
  "MARKET_OPEN",
  "MARKET_CLOSE",
  "AFTER_MARKET",
] as const;

function tableRowKey(row: Record<string, unknown>, fields: string[]): string {
  for (const field of fields) {
    const value = row[field];
    if (value !== null && value !== undefined && value !== "") {
      return String(value);
    }
  }
  try {
    return JSON.stringify(row);
  } catch {
    return "unknown-row";
  }
}

export default function UserAutoTradingPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const strategyStatusQuery = useQuery({
    queryKey: queryKeys.user.realtimeStrategy(),
    queryFn: userApi.getRealtimeStrategyStatus,
    refetchInterval: 5_000,
  });

  const executionStatusQuery = useQuery({
    queryKey: queryKeys.user.realtimeExecution(),
    queryFn: userApi.getRealtimeExecutionStatus,
    refetchInterval: 5_000,
  });

  const executionHistoryQuery = useQuery({
    queryKey: queryKeys.user.realtimeExecutionHistory(),
    queryFn: userApi.getRealtimeExecutionHistory,
    refetchInterval: 10_000,
  });

  const sessionsQuery = useQuery({
    queryKey: queryKeys.user.realtimeSessions(),
    queryFn: userApi.getRealtimeSessionsStatus,
    refetchInterval: 10_000,
  });

  const riskQuery = useQuery({
    queryKey: queryKeys.user.realtimeRisk(),
    queryFn: userApi.getRealtimeRiskStatus,
    refetchInterval: 15_000,
  });

  const killQuery = useQuery({
    queryKey: queryKeys.user.killSwitch(),
    queryFn: userApi.getKillSwitch,
    refetchInterval: 10_000,
  });

  const activeStrategyQuery = useQuery({
    queryKey: queryKeys.user.activeDeployment(DEFAULT_EXCHANGE),
    queryFn: () =>
      userApi.getActiveStrategyDeployment({
        market_code: DEFAULT_EXCHANGE,
        mode: "PAPER",
      }),
  });

  const runtimeQuery = useQuery({
    queryKey: queryKeys.user.strategyRuntime(),
    queryFn: userApi.getStrategyRuntimeStatus,
    refetchInterval: 10_000,
  });

  const invalidateAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.realtimeStrategy(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.realtimeExecution(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.realtimeExecutionHistory(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.realtimeSessions(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.killSwitch(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.realtimeRisk(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.strategyRuntime(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.activeDeployment(DEFAULT_EXCHANGE),
      }),
    ]);
  };

  const startAuto = useMutation({
    mutationFn: async () => {
      await userApi.startRealtimeStrategy();
      await userApi.startRealtimeExecution();
    },
    onSuccess: async () => {
      message.success("자동매매 ON (전략·체결 러너 시작)");
      await invalidateAll();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const stopAuto = useMutation({
    mutationFn: async () => {
      await userApi.stopRealtimeExecution();
      await userApi.stopRealtimeStrategy();
    },
    onSuccess: async () => {
      message.success("자동매매 OFF (전략·체결 러너 중지)");
      await invalidateAll();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const startScheduler = useMutation({
    mutationFn: userApi.startRealtimeSessionScheduler,
    onSuccess: async () => {
      message.success("예약 스케줄러 시작");
      await invalidateAll();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const stopScheduler = useMutation({
    mutationFn: userApi.stopRealtimeSessionScheduler,
    onSuccess: async () => {
      message.success("예약 스케줄러 중지");
      await invalidateAll();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const runPhase = useMutation({
    mutationFn: (phase: string) => userApi.runRealtimeSessionPhaseNow(phase),
    onSuccess: async (_data, phase) => {
      message.success(`세션 phase 실행: ${phase}`);
      await invalidateAll();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const strategyOn = isRunnerOn(strategyStatusQuery.data);
  const executionOn = isRunnerOn(executionStatusQuery.data);
  const autoOn = strategyOn || executionOn;

  const kill = asRecord(killQuery.data);
  const killActive =
    kill?.active === true ||
    String(kill?.status ?? "").toUpperCase() === "ACTIVE";

  const risk = asRecord(riskQuery.data);
  const sessions = asRecord(sessionsQuery.data);
  const schedulerRunning = Boolean(sessions?.running);
  const sessionJobs = extractRows(sessions?.jobs ?? sessionsQuery.data);

  const runtime = asRecord(runtimeQuery.data);
  const strategyStatus = asRecord(strategyStatusQuery.data);
  const executionStatus = asRecord(executionStatusQuery.data);

  const activeStrategies = useMemo(() => {
    const rows = extractRows(activeStrategyQuery.data);
    if (rows.length) return rows;
    const one = asRecord(activeStrategyQuery.data);
    return one ? [one] : [];
  }, [activeStrategyQuery.data]);

  const historyRows = useMemo(() => {
    const data = executionHistoryQuery.data;
    if (Array.isArray(data)) {
      return data.filter(
        (item): item is Record<string, unknown> =>
          typeof item === "object" && item !== null,
      );
    }
    return extractRows(data);
  }, [executionHistoryQuery.data]);

  const toggling = startAuto.isPending || stopAuto.isPending;

  return (
    <UserPageShell
      title="자동매매"
      description="ON/OFF · 실행 전략 · 예약 · Kill Switch · 위험관리 · 실행 로그 · STEP45"
      extra={
        <Space wrap>
          <Button size="small">
            <Link href={userRoutes.strategies}>전략</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.trading}>매매</Link>
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap size={8}>
          <Tag color={autoOn ? "success" : "default"}>
            Auto: {autoOn ? "ON" : "OFF"}
          </Tag>
          <Tag color={strategyOn ? "processing" : "default"}>
            Strategy runner: {strategyOn ? "RUNNING" : "STOPPED"}
          </Tag>
          <Tag color={executionOn ? "processing" : "default"}>
            Execution runner: {executionOn ? "RUNNING" : "STOPPED"}
          </Tag>
          <Tag color={killActive ? "error" : "success"}>
            Kill Switch: {killActive ? "ACTIVE" : "INACTIVE"}
          </Tag>
          <Tag color={schedulerRunning ? "processing" : "default"}>
            Scheduler: {schedulerRunning ? "RUNNING" : "STOPPED"}
          </Tag>
        </Space>

        {killActive ? (
          <Alert
            type="error"
            showIcon
            title="Kill Switch ACTIVE"
            description="자동·수동 주문이 차단될 수 있습니다. 해제는 Admin만 가능합니다."
          />
        ) : null}

        <Row gutter={[16, 16]}>
          {/* 자동매매 ON/OFF */}
          <Col xs={24} lg={12}>
            <Card
              title="자동매매 ON/OFF"
              size="small"
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  /realtime-strategy · /realtime-execution
                </Typography.Text>
              }
            >
              <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                <Space align="center" size={16}>
                  <Switch
                    checked={autoOn}
                    loading={toggling}
                    disabled={killActive}
                    onChange={(checked) => {
                      if (checked) {
                        startAuto.mutate();
                      } else {
                        stopAuto.mutate();
                      }
                    }}
                  />
                  <Typography.Text>
                    {autoOn ? "자동매매 실행 중" : "자동매매 중지"}
                  </Typography.Text>
                </Space>
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="전략 러너">
                    {strategyOn ? (
                      <Tag color="success">ON</Tag>
                    ) : (
                      <Tag>OFF</Tag>
                    )}
                    {" "}
                    {cell(strategyStatus?.status ?? strategyStatus?.state)}
                  </Descriptions.Item>
                  <Descriptions.Item label="체결 러너">
                    {executionOn ? (
                      <Tag color="success">ON</Tag>
                    ) : (
                      <Tag>OFF</Tag>
                    )}
                    {" "}
                    {cell(executionStatus?.status ?? executionStatus?.state)}
                  </Descriptions.Item>
                </Descriptions>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  ON = strategy start + execution start · OFF = execution stop +
                  strategy stop
                </Typography.Text>
              </Space>
            </Card>
          </Col>

          {/* Kill Switch */}
          <Col xs={24} lg={12}>
            <Card
              title="Kill Switch"
              size="small"
              loading={killQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /risk/kill-switch
                </Typography.Text>
              }
            >
              {killQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(killQuery.error).message}
                />
              ) : (
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="상태">
                    <Tag color={killActive ? "error" : "success"}>
                      {cell(kill?.status ?? (killActive ? "ACTIVE" : "INACTIVE"))}
                    </Tag>
                  </Descriptions.Item>
                  {Object.entries(kill ?? {})
                    .filter(([key]) => !["status", "active"].includes(key))
                    .slice(0, 6)
                    .map(([key, value]) => (
                      <Descriptions.Item key={key} label={key}>
                        {cell(value)}
                      </Descriptions.Item>
                    ))}
                </Descriptions>
              )}
              <div style={{ marginTop: 12 }}>
                {/* TODO: POST /risk/kill-switch/activate|deactivate — require_admin */}
                <UnimplementedNotice
                  feature="User Kill Switch 조작"
                  reason="activate/deactivate API는 Admin 권한(require_admin)입니다. User Web에서는 상태 조회만 제공합니다."
                  relatedApis={[
                    "GET /api/v1/risk/kill-switch",
                    "POST /api/v1/risk/kill-switch/activate (Admin)",
                    "POST /api/v1/risk/kill-switch/deactivate (Admin)",
                  ]}
                />
              </div>
            </Card>
          </Col>
        </Row>

        {/* 실행 전략 */}
        <Card
          title="실행 전략"
          size="small"
          loading={
            activeStrategyQuery.isLoading ||
            runtimeQuery.isLoading ||
            strategyStatusQuery.isLoading
          }
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /strategy-deployments/active · /strategy-runtime/status
            </Typography.Text>
          }
        >
          <Row gutter={[16, 16]}>
            <Col xs={24} md={10}>
              <Descriptions size="small" column={1} title="Runtime">
                {Object.entries(runtime ?? {})
                  .slice(0, 8)
                  .map(([key, value]) => (
                    <Descriptions.Item key={key} label={key}>
                      {cell(value)}
                    </Descriptions.Item>
                  ))}
                {Object.keys(runtime ?? {}).length === 0 ? (
                  <Descriptions.Item label="status">—</Descriptions.Item>
                ) : null}
              </Descriptions>
            </Col>
            <Col xs={24} md={14}>
              <Table
                size="small"
                pagination={false}
                rowKey={(row) =>
                  tableRowKey(row, [
                    "strategy_deployment_id",
                    "strategy_code",
                    "symbol",
                  ])
                }
                dataSource={activeStrategies.slice(0, 10)}
                locale={{ emptyText: "ACTIVE 배포 전략 없음" }}
                columns={[
                  {
                    title: "전략",
                    dataIndex: "strategy_code",
                    render: cell,
                  },
                  { title: "심볼", dataIndex: "symbol", render: cell },
                  {
                    title: "모드",
                    dataIndex: "mode_code",
                    width: 80,
                    render: (v) => cell(v ?? "PAPER"),
                  },
                  {
                    title: "상태",
                    dataIndex: "status_code",
                    width: 90,
                    render: (v) => (
                      <Tag color="success">{cell(v ?? "ACTIVE")}</Tag>
                    ),
                  },
                ]}
              />
            </Col>
          </Row>
        </Card>

        <Row gutter={[16, 16]}>
          {/* 예약 실행 */}
          <Col xs={24} lg={12}>
            <Card
              title="예약 실행"
              size="small"
              loading={sessionsQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  /realtime-sessions
                </Typography.Text>
              }
            >
              <Space orientation="vertical" size={12} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color={schedulerRunning ? "processing" : "default"}>
                    {schedulerRunning ? "스케줄러 RUNNING" : "스케줄러 STOPPED"}
                  </Tag>
                  <Button
                    type="primary"
                    size="small"
                    loading={startScheduler.isPending}
                    disabled={schedulerRunning}
                    onClick={() => startScheduler.mutate()}
                  >
                    스케줄러 시작
                  </Button>
                  <Button
                    danger
                    size="small"
                    loading={stopScheduler.isPending}
                    disabled={!schedulerRunning}
                    onClick={() => stopScheduler.mutate()}
                  >
                    스케줄러 중지
                  </Button>
                </Space>

                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  즉시 실행 (run-now)
                </Typography.Text>
                <Space wrap>
                  {SESSION_PHASES.map((phase) => (
                    <Button
                      key={phase}
                      size="small"
                      loading={
                        runPhase.isPending && runPhase.variables === phase
                      }
                      onClick={() => runPhase.mutate(phase)}
                    >
                      {phase}
                    </Button>
                  ))}
                </Space>

                <Table
                  size="small"
                  pagination={false}
                  rowKey={(row) => tableRowKey(row, ["id", "next_run_time"])}
                  dataSource={sessionJobs.slice(0, 10)}
                  locale={{ emptyText: "등록된 세션 잡 없음" }}
                  columns={[
                    { title: "Job", dataIndex: "id", render: cell },
                    {
                      title: "Next",
                      dataIndex: "next_run_time",
                      render: cell,
                    },
                  ]}
                />

                <UnimplementedNotice
                  feature="예약 잡 CRUD"
                  reason="세션 스케줄러 일괄 start/stop 과 phase run-now만 있습니다. 사용자별 예약 시간 CRUD API는 없습니다."
                  relatedApis={[
                    "GET /api/v1/realtime-sessions/status",
                    "POST /api/v1/realtime-sessions/start-scheduler",
                    "POST /api/v1/realtime-sessions/stop-scheduler",
                    "POST /api/v1/realtime-sessions/run-now/{phase}",
                    "TODO: GET/POST/DELETE /api/v1/user/auto-trading/schedules",
                  ]}
                />
              </Space>
            </Card>
          </Col>

          {/* 위험관리 상태 */}
          <Col xs={24} lg={12}>
            <Card
              title="위험관리 상태"
              size="small"
              loading={riskQuery.isLoading}
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  GET /realtime-risk/status
                </Typography.Text>
              }
            >
              {riskQuery.error ? (
                <Alert
                  type="warning"
                  showIcon
                  title={toApiError(riskQuery.error).message}
                />
              ) : (
                <Descriptions size="small" column={1}>
                  {Object.entries(risk ?? {}).map(([key, value]) => (
                    <Descriptions.Item key={key} label={key}>
                      {typeof value === "boolean" ? (
                        <Tag color={value ? "error" : "success"}>
                          {String(value)}
                        </Tag>
                      ) : (
                        cell(value)
                      )}
                    </Descriptions.Item>
                  ))}
                  {Object.keys(risk ?? {}).length === 0 ? (
                    <Descriptions.Item label="policy">—</Descriptions.Item>
                  ) : null}
                </Descriptions>
              )}
            </Card>
          </Col>
        </Row>

        {/* 실행 로그 */}
        <Card
          title="실행 로그"
          size="small"
          loading={executionHistoryQuery.isLoading}
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /realtime-execution/history
            </Typography.Text>
          }
        >
          {executionHistoryQuery.error ? (
            <Alert
              type="warning"
              showIcon
              title={toApiError(executionHistoryQuery.error).message}
            />
          ) : (
            <Table
              size="small"
              pagination={{ pageSize: 10 }}
              rowKey={(row) =>
                tableRowKey(row, [
                  "id",
                  "event_id",
                  "created_at",
                  "timestamp",
                  "symbol",
                ])
              }
              dataSource={historyRows.slice(0, 50)}
              locale={{ emptyText: "실행 이력 없음" }}
              columns={[
                {
                  title: "시각",
                  render: (_v, row) =>
                    cell(
                      row.created_at ??
                        row.timestamp ??
                        row.event_time ??
                        row.executed_at,
                    ),
                },
                {
                  title: "유형",
                  render: (_v, row) =>
                    cell(row.event_type ?? row.type ?? row.action),
                },
                {
                  title: "심볼",
                  dataIndex: "symbol",
                  render: cell,
                },
                {
                  title: "메시지",
                  ellipsis: true,
                  render: (_v, row) =>
                    cell(
                      row.message ??
                        row.detail ??
                        row.reason ??
                        row.status ??
                        row,
                    ),
                },
              ]}
            />
          )}
        </Card>
      </Space>
    </UserPageShell>
  );
}
