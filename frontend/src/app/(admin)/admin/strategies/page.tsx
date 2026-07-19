"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Card,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable, AdminJsonCard } from "@/features/admin/components/AdminPanels";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { PermissionButton } from "@/features/auth/components/PermissionButton";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export default function AdminStrategiesPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [paramJson, setParamJson] = useState("{}");

  const active = useQuery({
    queryKey: queryKeys.admin.activeDeployment("KRX"),
    queryFn: () => adminApi.getActiveDeployments({ market_code: "KRX", mode: "PAPER" }),
  });
  const ranking = useQuery({
    queryKey: queryKeys.admin.strategyRanking(),
    queryFn: adminApi.getStrategyRanking,
  });
  const selection = useQuery({
    queryKey: queryKeys.admin.strategySelection(),
    queryFn: adminApi.getStrategySelectorLatest,
  });
  const runtime = useQuery({
    queryKey: queryKeys.admin.strategyRuntime(),
    queryFn: adminApi.getStrategyRuntimeStatus,
  });
  const ops = useQuery({
    queryKey: queryKeys.dashboard.strategyOps(),
    queryFn: adminApi.getStrategyOpsDashboard,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: queryKeys.admin.activeDeployment("KRX") });
    void qc.invalidateQueries({ queryKey: queryKeys.admin.strategyRuntime() });
    void qc.invalidateQueries({ queryKey: queryKeys.dashboard.strategyOps() });
  };

  const registerAndDeploy = useMutation({
    mutationFn: async (v: {
      strategy_code: string;
      market_code: string;
      symbol?: string;
      run_type: string;
      parameter_payload: Record<string, unknown>;
    }) => {
      // 배포 검증: COMPLETED + WALK_FORWARD|PAPER 만 허용
      const runType =
        v.run_type === "BACKTEST" ? "PAPER" : v.run_type;

      const run = (await adminApi.createStrategyPerformanceRun({
        strategy_code: v.strategy_code,
        run_type: runType,
        market_code: v.market_code,
        symbol: v.symbol || null,
        period_start_date: daysAgoIso(30),
        period_end_date: todayIso(),
        parameter_payload: v.parameter_payload,
      })) as { strategy_performance_run_id?: number; run_id?: number };

      const runId = Number(
        run.strategy_performance_run_id ?? run.run_id ?? 0,
      );
      if (!runId) {
        throw new Error("performance run id를 받지 못했습니다");
      }

      await adminApi.completeStrategyPerformanceRun(runId);

      return adminApi.deployStrategy({
        strategy_code: v.strategy_code,
        strategy_performance_run_id: runId,
        market_code: v.market_code,
        symbol: v.symbol || null,
        mode: "PAPER",
        parameter_payload: v.parameter_payload,
        requested_by: "admin-web",
      });
    },
    onSuccess: () => {
      message.success("전략 등록·배포·활성화 완료 (PAPER)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const deployOnly = useMutation({
    mutationFn: adminApi.deployStrategy,
    onSuccess: () => {
      message.success("전략 배포·활성화 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const updateDeploy = useMutation({
    mutationFn: (v: {
      deployment_id: number;
      parameter_payload: Record<string, unknown>;
    }) =>
      adminApi.updateStrategyDeployment(v.deployment_id, {
        parameter_payload: v.parameter_payload,
        requested_by: "admin-web",
      }),
    onSuccess: () => {
      message.success("전략 수정(재배포) 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const stopDeploy = useMutation({
    mutationFn: (deploymentId: number) =>
      adminApi.stopStrategyDeployment(deploymentId),
    onSuccess: () => {
      message.success("전략 중지 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const reloadRuntime = useMutation({
    mutationFn: () => adminApi.reloadStrategyRuntime({ market_code: "KRX" }),
    onSuccess: () => {
      message.success("런타임 활성화(reload) 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const activeRow = useMemo(() => {
    const data = active.data;
    if (!data || typeof data !== "object") return null;
    return data as Record<string, unknown>;
  }, [active.data]);

  const parseParams = (): Record<string, unknown> | null => {
    try {
      const parsed = JSON.parse(paramJson || "{}") as unknown;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
      message.error("parameter_payload는 JSON 객체여야 합니다");
      return null;
    } catch {
      message.error("parameter_payload JSON 파싱 실패");
      return null;
    }
  };

  return (
    <AdminPageShell
      title="전략관리"
      description="등록 · 수정 · 배포 · 활성화(PAPER) · runtime reload"
      extra={
        <PermissionButton
          permission="trading:write"
          loading={reloadRuntime.isPending}
          onClick={() => reloadRuntime.mutate()}
        >
          런타임 활성화 (reload)
        </PermissionButton>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card title="전략 등록 + 배포 + 활성화" size="small">
          <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
            performance run 생성 후 PAPER 배포(즉시 ACTIVE). LIVE 배포는 서버에서 거부됩니다.
          </Typography.Paragraph>
          <Form
            layout="inline"
            onFinish={(v) => {
              const parameter_payload = parseParams();
              if (!parameter_payload) return;
              registerAndDeploy.mutate({
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
            }}
          >
            <Form.Item
              name="strategy_code"
              label="strategy_code"
              rules={[{ required: true }]}
            >
              <Input placeholder="SMA_CROSS" style={{ width: 140 }} />
            </Form.Item>
            <Form.Item name="market_code" label="market" rules={[{ required: true }]}>
              <Input style={{ width: 90 }} />
            </Form.Item>
            <Form.Item name="symbol" label="symbol">
              <Input allowClear style={{ width: 100 }} />
            </Form.Item>
            <Form.Item name="run_type" label="run_type">
              <Select
                style={{ width: 150 }}
                options={[
                  { value: "PAPER", label: "PAPER" },
                  { value: "WALK_FORWARD", label: "WALK_FORWARD" },
                ]}
              />
            </Form.Item>
            <PermissionButton
              permission="trading:write"
              type="primary"
              htmlType="submit"
              loading={registerAndDeploy.isPending}
            >
              등록·배포
            </PermissionButton>
          </Form>
          <Input.TextArea
            rows={3}
            value={paramJson}
            onChange={(e) => setParamJson(e.target.value)}
            placeholder='parameter_payload JSON e.g. {"fast":10,"slow":30}'
            style={{ marginTop: 12 }}
          />
        </Card>

        <Card title="기존 performance run으로 배포" size="small">
          <Form
            layout="inline"
            onFinish={(v) => {
              const parameter_payload = parseParams();
              if (!parameter_payload) return;
              deployOnly.mutate({
                strategy_code: v.strategy_code,
                strategy_performance_run_id: v.strategy_performance_run_id,
                market_code: v.market_code,
                symbol: v.symbol || null,
                mode: "PAPER",
                parameter_payload,
                requested_by: "admin-web",
              });
            }}
            initialValues={{ market_code: "KRX" }}
          >
            <Form.Item
              name="strategy_code"
              label="strategy_code"
              rules={[{ required: true }]}
            >
              <Input style={{ width: 140 }} />
            </Form.Item>
            <Form.Item
              name="strategy_performance_run_id"
              label="run_id"
              rules={[{ required: true }]}
            >
              <InputNumber min={1} />
            </Form.Item>
            <Form.Item name="market_code" label="market" rules={[{ required: true }]}>
              <Input style={{ width: 90 }} />
            </Form.Item>
            <Form.Item name="symbol" label="symbol">
              <Input allowClear style={{ width: 100 }} />
            </Form.Item>
            <PermissionButton
              permission="trading:write"
              type="primary"
              htmlType="submit"
              loading={deployOnly.isPending}
            >
              배포·활성화
            </PermissionButton>
          </Form>
        </Card>

        <Card title="활성 전략 수정 / 중지" size="small">
          <AdminJsonCard
            title="GET /strategy-deployments/active"
            loading={active.isLoading}
            error={active.error ? toApiError(active.error) : null}
            data={active.data}
          />
          <Space wrap style={{ marginTop: 12 }}>
            <PermissionButton
              permission="trading:write"
              loading={updateDeploy.isPending}
              disabled={!activeRow?.strategy_deployment_id}
              onClick={() => {
                const parameter_payload = parseParams();
                if (!parameter_payload) return;
                updateDeploy.mutate({
                  deployment_id: Number(activeRow?.strategy_deployment_id),
                  parameter_payload,
                });
              }}
            >
              파라미터 수정(재배포)
            </PermissionButton>
            <PermissionButton
              permission="trading:write"
              danger
              loading={stopDeploy.isPending}
              disabled={!activeRow?.strategy_deployment_id}
              onClick={() =>
                stopDeploy.mutate(Number(activeRow?.strategy_deployment_id))
              }
            >
              중지
            </PermissionButton>
          </Space>
        </Card>

        <AdminDataTable
          title="GET /strategy-ranking"
          loading={ranking.isLoading}
          error={ranking.error ? toApiError(ranking.error) : null}
          rowKey={(r) => cell(r.strategy_code ?? r.rank ?? JSON.stringify(r))}
          columns={[
            { title: "rank", dataIndex: "rank", sorter: true },
            { title: "strategy", dataIndex: "strategy_code" },
            { title: "score", dataIndex: "score" },
            { title: "run_id", dataIndex: "strategy_performance_run_id" },
          ]}
          dataSource={extractRows(ranking.data)}
        />
        <AdminJsonCard
          title="GET /strategy-selector/latest"
          loading={selection.isLoading}
          error={selection.error ? toApiError(selection.error) : null}
          data={selection.data}
        />
        <AdminJsonCard
          title="GET /strategy-runtime/status"
          loading={runtime.isLoading}
          error={runtime.error ? toApiError(runtime.error) : null}
          data={runtime.data}
        />
        <AdminJsonCard
          title="GET /dashboard/strategy-operations"
          loading={ops.isLoading}
          error={ops.error ? toApiError(ops.error) : null}
          data={ops.data}
        />
      </Space>
    </AdminPageShell>
  );
}
