"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";

import { asRecord, cell, extractRows } from "@/shared/utils/dataHelpers";
import { userRoutes } from "@/config/routes";
import { useAuth } from "@/features/auth/hooks/useAuth";
import { canAccessAdminPortal } from "@/features/auth/utils/roles";
import { UserPageShell } from "@/features/user/components/UserPageShell";
import { MarketSessionBanner } from "@/features/user/market/MarketSessionBanner";
import * as userApi from "@/features/user/api/userApi";
import { normalizeWeights } from "@/features/user/strategy/normalizeWeights";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import { UnimplementedNotice } from "@/shared/components/UnimplementedNotice";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

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

/** STEP 8-3 — 내 전략 / 공개 전략 패널 */
function OwnedStrategiesPanel({
  currentUserId,
  messageApi,
}: {
  currentUserId: number | null;
  messageApi: { success: (s: string) => void; error: (s: string) => void };
}) {
  const queryClient = useQueryClient();
  const [createForm] = Form.useForm();
  const [linkAccountId, setLinkAccountId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const mineQuery = useQuery({
    queryKey: queryKeys.user.ownedStrategies("MINE"),
    queryFn: () => userApi.listOwnedStrategies({ scope: "MINE", limit: 100 }),
  });
  const publicQuery = useQuery({
    queryKey: queryKeys.user.ownedStrategies("PUBLIC"),
    queryFn: () => userApi.listOwnedStrategies({ scope: "PUBLIC", limit: 100 }),
  });

  const invalidateOwned = () => {
    void queryClient.invalidateQueries({
      queryKey: ["user", "owned-strategies"],
    });
  };

  const createMut = useMutation({
    mutationFn: userApi.createOwnedStrategy,
    onSuccess: () => {
      messageApi.success("개인 전략을 생성했습니다");
      createForm.resetFields();
      invalidateOwned();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => userApi.deleteOwnedStrategy(id),
    onSuccess: () => {
      messageApi.success("전략을 비활성화(soft delete)했습니다");
      invalidateOwned();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
    onSettled: () => setBusyId(null),
  });

  const cloneMut = useMutation({
    mutationFn: (id: number) => userApi.cloneOwnedStrategy(id),
    onSuccess: () => {
      messageApi.success("공개 전략을 개인 전략으로 복제했습니다");
      invalidateOwned();
    },
    onError: (e) => messageApi.error(toApiError(e).message),
    onSettled: () => setBusyId(null),
  });

  const linkMut = useMutation({
    mutationFn: (strategyId: number) => {
      if (!linkAccountId || linkAccountId <= 0) {
        throw new Error("연결할 Paper 계좌 ID를 입력하세요");
      }
      return userApi.linkAccountStrategy(linkAccountId, strategyId, {
        account_type: "PAPER",
        account_broker: "PAPER",
      });
    },
    onSuccess: () => messageApi.success("계좌에 전략을 연결했습니다"),
    onError: (e) => messageApi.error(toApiError(e).message),
    onSettled: () => setBusyId(null),
  });

  const mineRows = extractRows(mineQuery.data);
  const publicRows = extractRows(publicQuery.data);

  const columnsFor = (kind: "MINE" | "PUBLIC") => [
    { title: "ID", dataIndex: "strategy_id", width: 70, render: cell },
    { title: "코드", dataIndex: "strategy_code", render: cell },
    { title: "이름", dataIndex: "name", render: cell },
    { title: "시장", dataIndex: "market_type", width: 80, render: cell },
    {
      title: "소유",
      dataIndex: "owner_type",
      width: 80,
      render: (v: unknown, row: Record<string, unknown>) => (
        <Space size={4}>
          <Tag>{cell(v)}</Tag>
          {kind === "MINE" ||
          (currentUserId != null &&
            Number(row.user_id) === Number(currentUserId)) ? (
            <Tag color="blue">내 전략</Tag>
          ) : (
            <Tag color="green">공개</Tag>
          )}
        </Space>
      ),
    },
    {
      title: "공개",
      dataIndex: "visibility",
      width: 80,
      render: cell,
    },
    {
      title: "활성",
      dataIndex: "is_active",
      width: 70,
      render: (v: unknown) => (v ? <Tag color="success">Y</Tag> : <Tag>N</Tag>),
    },
    {
      title: "승인",
      dataIndex: "approved_at",
      width: 90,
      render: (v: unknown) => (v ? <Tag color="purple">승인</Tag> : <Tag>—</Tag>),
    },
    {
      title: "작업",
      key: "actions",
      width: kind === "MINE" ? 280 : 240,
      render: (_: unknown, row: Record<string, unknown>) => {
        const id = Number(row.strategy_id);
        const loading = busyId === id;
        if (kind === "MINE") {
          return (
            <Space wrap size={4}>
              <Button
                size="small"
                disabled={loading || deleteMut.isPending}
                loading={loading && deleteMut.isPending}
                danger
                onClick={() => {
                  setBusyId(id);
                  deleteMut.mutate(id);
                }}
              >
                삭제
              </Button>
              <Button
                size="small"
                disabled={loading || linkMut.isPending}
                loading={loading && linkMut.isPending}
                onClick={() => {
                  setBusyId(id);
                  linkMut.mutate(id);
                }}
              >
                계좌 연결
              </Button>
              <Button
                size="small"
                disabled={loading || cloneMut.isPending}
                onClick={() => {
                  setBusyId(id);
                  cloneMut.mutate(id);
                }}
              >
                복제
              </Button>
            </Space>
          );
        }
        return (
          <Space wrap size={4}>
            <Button
              size="small"
              disabled={loading || cloneMut.isPending}
              loading={loading && cloneMut.isPending}
              onClick={() => {
                setBusyId(id);
                cloneMut.mutate(id);
              }}
            >
              복제
            </Button>
            <Button
              size="small"
              disabled={loading || linkMut.isPending}
              loading={loading && linkMut.isPending}
              onClick={() => {
                setBusyId(id);
                linkMut.mutate(id);
              }}
            >
              계좌 연결
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <Card
      size="small"
      title="내 전략 · 공개 전략"
      extra={
        <Space>
          <Typography.Text type="secondary">Paper 계좌 ID</Typography.Text>
          <InputNumber
            min={1}
            size="small"
            value={linkAccountId ?? undefined}
            onChange={(v) => setLinkAccountId(typeof v === "number" ? v : null)}
          />
        </Space>
      }
    >
      <Space orientation="vertical" size={12} style={{ width: "100%" }}>
        <Form
          form={createForm}
          layout="inline"
          onFinish={(v) =>
            createMut.mutate({
              strategy_code: String(v.strategy_code),
              name: String(v.name),
              market_type: String(v.market_type || "STOCK"),
              description: v.description || null,
              parameter_payload: {},
            })
          }
        >
          <Form.Item
            name="strategy_code"
            label="코드"
            rules={[{ required: true }]}
          >
            <Input placeholder="MY_MA" />
          </Form.Item>
          <Form.Item name="name" label="이름" rules={[{ required: true }]}>
            <Input placeholder="내 이동평균" />
          </Form.Item>
          <Form.Item name="market_type" label="시장" initialValue="STOCK">
            <Select
              style={{ width: 110 }}
              options={[
                { value: "STOCK", label: "STOCK" },
                { value: "CRYPTO", label: "CRYPTO" },
                { value: "ALL", label: "ALL" },
              ]}
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={createMut.isPending}
              disabled={createMut.isPending}
            >
              개인 전략 생성
            </Button>
          </Form.Item>
        </Form>

        <Typography.Text strong>내 전략</Typography.Text>
        <Table
          size="small"
          loading={mineQuery.isLoading}
          pagination={{ pageSize: 5 }}
          rowKey={(r) => String(asRecord(r)?.strategy_id ?? "mine")}
          dataSource={mineRows}
          columns={columnsFor("MINE")}
          locale={{ emptyText: "내 전략 없음" }}
        />

        <Typography.Text strong>공개 전략</Typography.Text>
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          공개 전략은 상세·복제·백테스트·계좌 연결만 가능합니다 (수정·삭제 버튼 없음).
        </Typography.Paragraph>
        <Table
          size="small"
          loading={publicQuery.isLoading}
          pagination={{ pageSize: 5 }}
          rowKey={(r) => String(asRecord(r)?.strategy_id ?? "public")}
          dataSource={publicRows}
          columns={columnsFor("PUBLIC")}
          locale={{ emptyText: "공개 전략 없음" }}
        />
      </Space>
    </Card>
  );
}

export default function UserStrategiesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const actor = user?.username ?? "user-web";
  // 전략 배포·런타임 제어는 admin 전용 — 조회는 회원 누구나 가능
  const canOperate = canAccessAdminPortal(user?.roles);

  const [paramJson, setParamJson] = useState('{"fast":5,"slow":20}');
  const [updateJson, setUpdateJson] = useState("{}");
  const [selectedDeploymentId, setSelectedDeploymentId] = useState<number | null>(
    null,
  );
  const [walkForwardResult, setWalkForwardResult] = useState<unknown>(null);
  const [portfolioResult, setPortfolioResult] = useState<unknown>(null);
  const [backtestResult, setBacktestResult] = useState<unknown>(null);

  const activeQuery = useQuery({
    queryKey: queryKeys.user.activeDeployment("KRX"),
    queryFn: () =>
      userApi.getActiveStrategyDeployment({
        market_code: "KRX",
        mode: "PAPER",
      }),
    refetchInterval: 10_000,
  });

  const rankingQuery = useQuery({
    queryKey: queryKeys.user.strategyRanking(),
    queryFn: userApi.getStrategyRanking,
  });

  const selectionQuery = useQuery({
    queryKey: queryKeys.user.strategySelection(),
    queryFn: userApi.getLatestStrategySelection,
  });

  const opsQuery = useQuery({
    queryKey: queryKeys.user.strategyOps(),
    queryFn: userApi.getStrategyOpsDashboard,
  });

  const runtimeQuery = useQuery({
    queryKey: queryKeys.user.strategyRuntime(),
    queryFn: userApi.getStrategyRuntimeStatus,
    refetchInterval: 10_000,
  });

  const myRuntimesQuery = useQuery({
    queryKey: ["user", "my-runtimes"],
    queryFn: () => userApi.listMyRuntimes(),
    refetchInterval: 10_000,
  });

  const realtimeQuery = useQuery({
    queryKey: queryKeys.user.realtimeStrategy(),
    queryFn: userApi.getRealtimeStrategyStatus,
    refetchInterval: 10_000,
  });

  const realtimeScopesQuery = useQuery({
    queryKey: ["user", "realtime-scopes"],
    queryFn: userApi.listMyRealtimeScopes,
    refetchInterval: 10_000,
  });

  const backtestRunsQuery = useQuery({
    queryKey: queryKeys.user.backtestRuns(),
    queryFn: () => userApi.listBacktestRuns({ limit: 20 }),
  });

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.activeDeployment("KRX"),
      }),
      queryClient.invalidateQueries({ queryKey: queryKeys.user.strategyOps() }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.strategyRuntime(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.realtimeStrategy(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.strategyRanking(),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.user.backtestRuns(),
      }),
    ]);
  };

  const parseJsonObject = (
    raw: string,
    label: string,
  ): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(raw || "{}") as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
      message.error(`${label}은(는) JSON 객체여야 합니다`);
      return null;
    } catch {
      message.error(`${label} JSON 파싱 실패`);
      return null;
    }
  };

  const createStrategy = useMutation({
    mutationFn: async (v: {
      strategy_code: string;
      market_code: string;
      symbol?: string;
      run_type: string;
      parameter_payload: Record<string, unknown>;
    }) => {
      const runType = v.run_type === "BACKTEST" ? "PAPER" : v.run_type;
      const run = (await userApi.createStrategyPerformanceRun({
        strategy_code: v.strategy_code,
        run_type: runType,
        market_code: v.market_code,
        symbol: v.symbol || null,
        period_start_date: daysAgoIso(30),
        period_end_date: todayIso(),
        parameter_payload: v.parameter_payload,
      })) as { strategy_performance_run_id?: number; run_id?: number };

      const runId = Number(run.strategy_performance_run_id ?? run.run_id ?? 0);
      if (!runId) {
        throw new Error("performance run id를 받지 못했습니다");
      }
      await userApi.completeStrategyPerformanceRun(runId);
      return userApi.deployStrategy({
        strategy_code: v.strategy_code,
        strategy_performance_run_id: runId,
        market_code: v.market_code,
        symbol: v.symbol || null,
        mode: "PAPER",
        parameter_payload: v.parameter_payload,
        requested_by: actor,
      });
    },
    onSuccess: async () => {
      message.success("전략 생성·배포 완료 (PAPER)");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const updateStrategy = useMutation({
    mutationFn: (v: {
      deployment_id: number;
      parameter_payload: Record<string, unknown>;
    }) =>
      userApi.updateStrategyDeployment(v.deployment_id, {
        parameter_payload: v.parameter_payload,
        requested_by: actor,
      }),
    onSuccess: async () => {
      message.success("전략 수정(재배포) 완료");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const stopStrategy = useMutation({
    mutationFn: (deploymentId: number) =>
      userApi.stopStrategyDeployment(deploymentId, {
        actor,
        reason: "Stopped from User Web",
      }),
    onSuccess: async () => {
      message.success("전략 중지 완료");
      setSelectedDeploymentId(null);
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const startRuntime = useMutation({
    mutationFn: async () => {
      await userApi.reloadStrategyRuntime({ market_code: "KRX" });
      return userApi.startRealtimeStrategy();
    },
    onSuccess: async () => {
      message.success("전략 실행(런타임 reload + realtime start)");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const stopRuntime = useMutation({
    mutationFn: userApi.stopRealtimeStrategy,
    onSuccess: async () => {
      message.success("전략 런타임 중지");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const runBacktest = useMutation({
    mutationFn: userApi.runMovingAverageBacktest,
    onSuccess: async (data) => {
      setBacktestResult(data);
      message.success("백테스트 완료");
      await invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const runWalkForward = useMutation({
    mutationFn: userApi.runWalkForward,
    onSuccess: (data) => {
      setWalkForwardResult(data);
      message.success("Walk Forward 완료");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const runPortfolioBt = useMutation({
    mutationFn: userApi.runPortfolioBacktest,
    onSuccess: (data) => {
      setPortfolioResult(data);
      message.success("포트폴리오 백테스트 완료");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const activeRow = useMemo(() => {
    const data = activeQuery.data;
    if (!data) return null;
    const rows = extractRows(data);
    if (rows.length) return rows[0];
    return asRecord(data);
  }, [activeQuery.data]);

  const activeId = Number(
    activeRow?.strategy_deployment_id ?? selectedDeploymentId ?? 0,
  );

  const rankingRows = extractRows(rankingQuery.data);
  const opsData = asRecord(opsQuery.data);
  const recentDeployments = extractRows(
    opsData?.recent_deployments ?? opsData?.deployments,
  );
  const runtime = asRecord(runtimeQuery.data);
  const realtime = asRecord(realtimeQuery.data);
  const backtestRuns = extractRows(backtestRunsQuery.data);
  const wf = asRecord(walkForwardResult);
  const wfWindows = extractRows(wf?.windows ?? wf?.results ?? walkForwardResult);
  const pf = asRecord(portfolioResult);
  const pfSummary = asRecord(pf?.summary);
  const bt = asRecord(backtestResult);

  const listRows =
    recentDeployments.length > 0
      ? recentDeployments
      : activeRow
        ? [activeRow]
        : rankingRows.slice(0, 20).map((row) => ({
            ...row,
            status_code: "RANKED",
            strategy_deployment_id: null,
          }));

  return (
    <UserPageShell
      title="전략"
      description="목록 · 생성 · 수정 · 실행 · 중지 · 백테스트 · Walk Forward · STEP46"
      extra={
        <Space wrap>
          <Button size="small">
            <Link href={userRoutes.autoTrading}>자동매매</Link>
          </Button>
          <Button size="small">
            <Link href={userRoutes.backtests}>백테스트</Link>
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <MarketSessionBanner exchangeCode="KRX" />

        <Alert
          type="info"
          showIcon
          title="전략 소유권 (STEP 8-3)"
          description="내 개인 전략과 공개(시스템·승인) 전략을 구분합니다. 공개 전략 원본은 수정·삭제할 수 없으며 복제 후 사용하세요."
        />

        <OwnedStrategiesPanel
          currentUserId={
            user?.id != null && user.id !== ""
              ? Number(user.id)
              : null
          }
          messageApi={message}
        />

        <Alert
          type="info"
          showIcon
          title="Backend 매핑"
          description="생성=performance run+deploy · 수정=update · 중지=stop · 실행=runtime reload+realtime start · 백테스트=/backtests/moving-average · WF=/walk-forward. 삭제·포트폴리오 최적화 API는 없음."
        />

        {!canOperate ? (
          <Alert
            type="warning"
            showIcon
            title="전략 배포·실행 제어는 운영자 이상 권한이 필요합니다"
            description="전략 목록·순위·실행 상태 조회는 누구나 가능합니다. 배포 생성·수정·중지, 런타임 실행·중지는 admin 권한 계정에서만 가능합니다."
          />
        ) : null}

        {/* 실행 상태 */}
        <Card size="small" title="전략 실행 · 중지" loading={runtimeQuery.isLoading}>
          <Space wrap>
            <Tag color="processing">
              Registry:{" "}
              {cell(
                (runtime as { scoped_runtime_count?: number } | null)
                  ?.scoped_runtime_count ?? "—",
              )}{" "}
              scopes
            </Tag>
            <Tag>
              Realtime: {cell(realtime?.status ?? realtime?.running ?? "—")}
            </Tag>
            {(() => {
              const items =
                realtimeScopesQuery.data &&
                typeof realtimeScopesQuery.data === "object" &&
                "items" in realtimeScopesQuery.data &&
                Array.isArray(
                  (realtimeScopesQuery.data as { items?: unknown }).items,
                )
                  ? (
                      realtimeScopesQuery.data as {
                        items: Record<string, unknown>[];
                      }
                    ).items
                  : [];
              const first = items[0];
              if (!first) {
                return <Tag>Scope 구독 없음</Tag>;
              }
              return (
                <>
                  <Tag color="blue">
                    Warm-up: {cell(first.warmup_status ?? "—")}
                  </Tag>
                  <Tag>
                    상태: {cell(first.runtime_status ?? "—")}
                  </Tag>
                  <Tag>
                    마지막 신호: {cell(first.last_signal_at ?? "—")}
                  </Tag>
                </>
              );
            })()}
            {activeRow ? (
              <Tag color="success">
                Active #{cell(activeRow.strategy_deployment_id)}{" "}
                {cell(activeRow.strategy_code)}
              </Tag>
            ) : (
              <Tag>Active 없음</Tag>
            )}
            <Button
              type="primary"
              disabled={!canOperate}
              loading={startRuntime.isPending}
              onClick={() => startRuntime.mutate()}
            >
              전략 실행
            </Button>
            <Button
              disabled={!canOperate}
              loading={stopRuntime.isPending}
              onClick={() => stopRuntime.mutate()}
            >
              런타임 중지
            </Button>
            <Button
              danger
              disabled={
                !canOperate || !Number.isFinite(activeId) || activeId <= 0
              }
              loading={stopStrategy.isPending}
              onClick={() => {
                if (activeId > 0) stopStrategy.mutate(activeId);
              }}
            >
              배포 중지
            </Button>
          </Space>
        </Card>

        <Card
          size="small"
          title="내 Scope Runtime"
          loading={myRuntimesQuery.isLoading}
        >
          <Table
            size="small"
            rowKey={(r) => String((r as { scope_key?: string }).scope_key)}
            pagination={false}
            dataSource={myRuntimesQuery.data?.items ?? []}
            locale={{ emptyText: "연결된 Scope Runtime이 없습니다." }}
            columns={[
              {
                title: "거래소/증권사",
                dataIndex: "broker_code",
                width: 80,
              },
              {
                title: "Market",
                dataIndex: "market_type",
                width: 80,
              },
              {
                title: "전략",
                dataIndex: "strategy_id",
                width: 90,
              },
              {
                title: "상태",
                dataIndex: "status",
                render: (v: string) => <Tag>{v}</Tag>,
              },
              {
                title: "Pause/오류",
                key: "pause",
                render: (_: unknown, row: Record<string, unknown>) =>
                  String(row.pause_reason ?? row.last_error ?? "-"),
              },
            ]}
          />
        </Card>

        {/* 전략 목록 */}
        <Card
          title="전략 목록"
          size="small"
          loading={
            opsQuery.isLoading ||
            activeQuery.isLoading ||
            rankingQuery.isLoading
          }
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              GET /user/strategies/operations-dashboard ·
              /strategy-deployments/active · /user/strategies/ranking
            </Typography.Text>
          }
        >
          <Table
            size="small"
            pagination={{ pageSize: 10 }}
            rowKey={(row) =>
              tableRowKey(row, [
                "strategy_deployment_id",
                "strategy_code",
                "symbol",
                "created_at",
              ])
            }
            dataSource={listRows}
            locale={{ emptyText: "전략 없음" }}
            rowSelection={{
              type: "radio",
              selectedRowKeys:
                selectedDeploymentId != null
                  ? [String(selectedDeploymentId)]
                  : activeId > 0
                    ? [String(activeId)]
                    : [],
              onChange: (keys) => {
                const id = Number(keys[0]);
                setSelectedDeploymentId(Number.isFinite(id) ? id : null);
              },
              getCheckboxProps: (row) => ({
                disabled: !row.strategy_deployment_id,
              }),
            }}
            columns={[
              {
                title: "배포ID",
                dataIndex: "strategy_deployment_id",
                width: 90,
                render: cell,
              },
              {
                title: "전략",
                dataIndex: "strategy_code",
                render: cell,
              },
              { title: "심볼", dataIndex: "symbol", render: cell },
              {
                title: "모드",
                dataIndex: "mode_code",
                render: (v) => cell(v ?? "PAPER"),
              },
              {
                title: "상태",
                dataIndex: "status_code",
                render: (v) => <Tag>{cell(v)}</Tag>,
              },
            ]}
          />
        </Card>

        <Row gutter={[16, 16]}>
          {/* 전략 생성 */}
          <Col xs={24} lg={12}>
            <Card
              title="전략 생성"
              size="small"
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  performance run → deploy
                </Typography.Text>
              }
            >
              <Form
                layout="vertical"
                disabled={!canOperate}
                onFinish={(v) => {
                  const parameter_payload = parseJsonObject(
                    paramJson,
                    "parameter_payload",
                  );
                  if (!parameter_payload) return;
                  createStrategy.mutate({
                    strategy_code: v.strategy_code,
                    market_code: v.market_code,
                    symbol: v.symbol || undefined,
                    run_type: v.run_type,
                    parameter_payload,
                  });
                }}
                initialValues={{
                  market_code: "KRX",
                  run_type: "PAPER",
                  strategy_code: "MA_CROSS",
                }}
              >
                <Form.Item
                  name="strategy_code"
                  label="전략코드"
                  rules={[{ required: true }]}
                >
                  <Input />
                </Form.Item>
                <Form.Item
                  name="market_code"
                  label="시장"
                  rules={[{ required: true }]}
                >
                  <Input />
                </Form.Item>
                <Form.Item name="symbol" label="심볼">
                  <Input placeholder="선택" />
                </Form.Item>
                <Form.Item name="run_type" label="run_type">
                  <Select
                    options={[
                      { value: "PAPER", label: "PAPER" },
                      { value: "WALK_FORWARD", label: "WALK_FORWARD" },
                    ]}
                  />
                </Form.Item>
                <Form.Item label="params JSON">
                  <Input.TextArea
                    value={paramJson}
                    onChange={(e) => setParamJson(e.target.value)}
                    rows={2}
                  />
                </Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={createStrategy.isPending}
                >
                  생성·배포
                </Button>
              </Form>
            </Card>
          </Col>

          {/* 전략 수정 */}
          <Col xs={24} lg={12}>
            <Card
              title="전략 수정"
              size="small"
              extra={
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  POST /strategy-deployments/{"{id}"}/update
                </Typography.Text>
              }
            >
              <Form
                layout="vertical"
                disabled={!canOperate}
                onFinish={() => {
                  const id =
                    selectedDeploymentId ??
                    (Number.isFinite(activeId) && activeId > 0
                      ? activeId
                      : null);
                  if (!id) {
                    message.warning("수정할 배포를 목록에서 선택하세요");
                    return;
                  }
                  const parameter_payload = parseJsonObject(
                    updateJson,
                    "parameter_payload",
                  );
                  if (!parameter_payload) return;
                  updateStrategy.mutate({
                    deployment_id: id,
                    parameter_payload,
                  });
                }}
              >
                <Form.Item label="배포ID">
                  <InputNumber
                    min={1}
                    style={{ width: "100%" }}
                    value={
                      selectedDeploymentId ?? (activeId > 0 ? activeId : null)
                    }
                    onChange={(v) =>
                      setSelectedDeploymentId(typeof v === "number" ? v : null)
                    }
                  />
                </Form.Item>
                <Form.Item label="params JSON">
                  <Input.TextArea
                    value={updateJson}
                    onChange={(e) => setUpdateJson(e.target.value)}
                    rows={2}
                  />
                </Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={updateStrategy.isPending}
                >
                  수정(재배포)
                </Button>
              </Form>
            </Card>
          </Col>
        </Row>

        {/* 전략 삭제 — API 없음 */}
        <Card title="전략 삭제" size="small">
          {/* TODO: DELETE /api/v1/strategy-deployments/{id} */}
          <UnimplementedNotice
            feature="전략 삭제"
            reason="Backend에 전략/배포 삭제(DELETE) API가 없습니다. 중지는 POST .../stop 으로 가능합니다."
            relatedApis={[
              "POST /api/v1/strategy-deployments/{id}/stop",
              "TODO: DELETE /api/v1/strategy-deployments/{id}",
            ]}
          />
        </Card>

        {/* 백테스트 */}
        <Card
          title="백테스트"
          size="small"
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              POST /user/backtests/moving-average · GET /user/backtests/runs
            </Typography.Text>
          }
        >
          <Form
            layout="inline"
            onFinish={(v: {
              exchange_code: string;
              symbol: string;
              initial_capital: number;
              short_window: number;
              long_window: number;
            }) => {
              runBacktest.mutate({
                exchange_code: v.exchange_code.trim().toUpperCase(),
                symbol: v.symbol.trim().toUpperCase(),
                start_date: daysAgoIso(90),
                end_date: todayIso(),
                initial_capital: v.initial_capital,
                short_window: v.short_window,
                long_window: v.long_window,
              });
            }}
            initialValues={{
              exchange_code: "KRX",
              symbol: "005930",
              initial_capital: 10_000_000,
              short_window: 5,
              long_window: 20,
            }}
          >
            <Form.Item
              name="exchange_code"
              label="거래소"
              rules={[{ required: true }]}
            >
              <Input style={{ width: 90 }} />
            </Form.Item>
            <Form.Item name="symbol" label="종목" rules={[{ required: true }]}>
              <Input style={{ width: 110 }} />
            </Form.Item>
            <Form.Item
              name="initial_capital"
              label="자본"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="short_window" label="단기">
              <InputNumber min={2} />
            </Form.Item>
            <Form.Item name="long_window" label="장기">
              <InputNumber min={3} />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={runBacktest.isPending}
            >
              MA 백테스트 실행
            </Button>
          </Form>

          {bt ? (
            <Descriptions
              size="small"
              column={2}
              style={{ marginTop: 12 }}
              title="최근 실행 결과"
            >
              {Object.entries(bt)
                .filter(([key]) => key !== "equity_curve" && key !== "trades")
                .slice(0, 10)
                .map(([key, value]) => (
                  <Descriptions.Item key={key} label={key}>
                    {cell(value)}
                  </Descriptions.Item>
                ))}
            </Descriptions>
          ) : null}

          <Table
            style={{ marginTop: 12 }}
            size="small"
            pagination={false}
            loading={backtestRunsQuery.isLoading}
            rowKey={(row) =>
              tableRowKey(row, ["backtest_run_id", "created_at", "symbol"])
            }
            dataSource={backtestRuns.slice(0, 10)}
            locale={{ emptyText: "저장된 백테스트 run 없음" }}
            columns={[
              {
                title: "ID",
                dataIndex: "backtest_run_id",
                width: 80,
                render: cell,
              },
              { title: "심볼", dataIndex: "symbol", render: cell },
              {
                title: "전략",
                dataIndex: "strategy_code",
                render: cell,
              },
              {
                title: "상태",
                dataIndex: "status_code",
                render: (v) => <Tag>{cell(v)}</Tag>,
              },
              { title: "시각", dataIndex: "created_at", render: cell },
            ]}
          />
        </Card>

        {/* Walk Forward */}
        <Card
          title="Walk Forward 결과"
          size="small"
          extra={
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              POST /user/backtests/walk-forward
            </Typography.Text>
          }
        >
          <Form
            layout="inline"
            onFinish={(v: {
              exchange_code: string;
              symbol: string;
              initial_capital: number;
            }) => {
              runWalkForward.mutate({
                exchange_code: v.exchange_code.trim().toUpperCase(),
                symbol: v.symbol.trim().toUpperCase(),
                start_date: daysAgoIso(365),
                end_date: todayIso(),
                initial_capital: v.initial_capital,
              });
            }}
            initialValues={{
              exchange_code: "KRX",
              symbol: "005930",
              initial_capital: 10_000_000,
            }}
          >
            <Form.Item
              name="exchange_code"
              label="거래소"
              rules={[{ required: true }]}
            >
              <Input style={{ width: 90 }} />
            </Form.Item>
            <Form.Item name="symbol" label="종목" rules={[{ required: true }]}>
              <Input style={{ width: 110 }} />
            </Form.Item>
            <Form.Item
              name="initial_capital"
              label="자본"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} style={{ width: 140 }} />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={runWalkForward.isPending}
            >
              Walk Forward 실행
            </Button>
          </Form>

          {wf ? (
            <>
              <Descriptions
                size="small"
                column={2}
                style={{ marginTop: 12 }}
                title="요약"
              >
                {Object.entries(wf)
                  .filter(
                    ([key]) =>
                      ![
                        "windows",
                        "results",
                        "report_text",
                        "equity_curve",
                      ].includes(key),
                  )
                  .slice(0, 8)
                  .map(([key, value]) => (
                    <Descriptions.Item key={key} label={key}>
                      {cell(value)}
                    </Descriptions.Item>
                  ))}
              </Descriptions>
              {wfWindows.length > 0 ? (
                <Table
                  style={{ marginTop: 12 }}
                  size="small"
                  pagination={false}
                  rowKey={(row) =>
                    tableRowKey(row, [
                      "window_no",
                      "test_start_date",
                      "train_start_date",
                    ])
                  }
                  dataSource={wfWindows.slice(0, 12)}
                  columns={[
                    {
                      title: "Window",
                      dataIndex: "window_no",
                      width: 80,
                      render: cell,
                    },
                    {
                      title: "Train",
                      render: (_v, row) =>
                        `${cell(row.train_start_date)} ~ ${cell(row.train_end_date)}`,
                    },
                    {
                      title: "Test",
                      render: (_v, row) =>
                        `${cell(row.test_start_date)} ~ ${cell(row.test_end_date)}`,
                    },
                    {
                      title: "수익",
                      dataIndex: "total_return_rate",
                      render: (v, row) =>
                        cell(v ?? row.return_rate ?? row.total_return),
                    },
                  ]}
                />
              ) : null}
              {typeof wf.report_text === "string" ? (
                <Typography.Paragraph
                  type="secondary"
                  style={{ marginTop: 12, fontSize: 12, whiteSpace: "pre-wrap" }}
                >
                  {wf.report_text.slice(0, 1200)}
                  {wf.report_text.length > 1200 ? "…" : ""}
                </Typography.Paragraph>
              ) : null}
            </>
          ) : (
            <Typography.Text type="secondary" style={{ display: "block", marginTop: 8 }}>
              실행 후 결과가 여기에 표시됩니다
            </Typography.Text>
          )}
        </Card>

        {/* 포트폴리오 최적화 — API 없음 / 가중치 백테스트는 참고 연결 */}
        <Card
          title="포트폴리오 최적화 결과"
          size="small"
        >
          {/* TODO: POST /api/v1/portfolio-optimize — 최적 가중치 산출 API 없음 */}
          <UnimplementedNotice
            feature="포트폴리오 최적화"
            reason="최적 가중치(예: mean-variance)를 산출하는 API가 Backend에 없습니다. 아래는 가중치를 직접 넣는 포트폴리오 백테스트입니다."
            relatedApis={[
              "TODO: POST /api/v1/portfolio-optimize",
              "참고: POST /api/v1/user/backtests/portfolio",
            ]}
          />

          <Typography.Title level={5} style={{ marginTop: 16 }}>
            참고 · 가중치 포트폴리오 백테스트
          </Typography.Title>
          <Form
            layout="inline"
            onFinish={(v: {
              symbol_a: string;
              weight_a: number;
              symbol_b: string;
              weight_b: number;
              initial_capital: number;
            }) => {
              const [wa, wb] = normalizeWeights([
                Number(v.weight_a),
                Number(v.weight_b),
              ]);
              if (wa + wb <= 0) {
                message.error("가중치 합이 0보다 커야 합니다");
                return;
              }
              runPortfolioBt.mutate({
                assets: [
                  {
                    exchange_code: "KRX",
                    symbol: v.symbol_a.trim().toUpperCase(),
                    weight: wa,
                  },
                  {
                    exchange_code: "KRX",
                    symbol: v.symbol_b.trim().toUpperCase(),
                    weight: wb,
                  },
                ],
                start_date: daysAgoIso(180),
                end_date: todayIso(),
                initial_capital: v.initial_capital,
              });
            }}
            initialValues={{
              symbol_a: "005930",
              weight_a: 0.6,
              symbol_b: "000660",
              weight_b: 0.4,
              initial_capital: 10_000_000,
            }}
          >
            <Form.Item name="symbol_a" label="종목A" rules={[{ required: true }]}>
              <Input style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="weight_a" label="가중A" rules={[{ required: true }]}>
              <InputNumber min={0.01} max={1} step={0.05} />
            </Form.Item>
            <Form.Item name="symbol_b" label="종목B" rules={[{ required: true }]}>
              <Input style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="weight_b" label="가중B" rules={[{ required: true }]}>
              <InputNumber min={0.01} max={1} step={0.05} />
            </Form.Item>
            <Form.Item
              name="initial_capital"
              label="자본"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} style={{ width: 140 }} />
            </Form.Item>
            <Button
              htmlType="submit"
              loading={runPortfolioBt.isPending}
            >
              포트폴리오 BT 실행
            </Button>
          </Form>

          {pfSummary || pf ? (
            <Descriptions
              size="small"
              column={2}
              style={{ marginTop: 12 }}
              title="포트폴리오 BT 요약"
            >
              {Object.entries(pfSummary ?? pf ?? {})
                .filter(
                  ([key]) =>
                    !["equity_curve", "assets", "failures", "report_text"].includes(
                      key,
                    ),
                )
                .slice(0, 10)
                .map(([key, value]) => (
                  <Descriptions.Item key={key} label={key}>
                    {cell(value)}
                  </Descriptions.Item>
                ))}
            </Descriptions>
          ) : null}
        </Card>

        {/* 보조: 랭킹 */}
        <Card
          title="전략 랭킹 · 셀렉터"
          size="small"
          loading={rankingQuery.isLoading || selectionQuery.isLoading}
        >
          {(rankingQuery.error || selectionQuery.error) && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              title={
                toApiError(rankingQuery.error ?? selectionQuery.error!).message
              }
            />
          )}
          <Table
            size="small"
            pagination={false}
            rowKey={(row) =>
              tableRowKey(row, ["strategy_code", "rank", "symbol"])
            }
            dataSource={rankingRows.slice(0, 10)}
            locale={{ emptyText: "랭킹 없음" }}
            columns={[
              { title: "전략", dataIndex: "strategy_code", render: cell },
              {
                title: "점수",
                dataIndex: "score",
                render: (v, row) => cell(v ?? row.rank_score),
              },
              { title: "순위", dataIndex: "rank", render: cell },
            ]}
          />
          {selectionQuery.data ? (
            <Typography.Paragraph
              type="secondary"
              style={{ marginTop: 12, marginBottom: 0, fontSize: 12 }}
            >
              selector/latest:{" "}
              {cell(asRecord(selectionQuery.data)?.strategy_code)}
            </Typography.Paragraph>
          ) : null}
        </Card>
      </Space>
    </UserPageShell>
  );
}
