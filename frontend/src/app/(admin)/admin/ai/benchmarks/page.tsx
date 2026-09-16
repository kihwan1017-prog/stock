"use client";

/**
 * STEP 11-8 — AI 벤치마크 / 스코어카드.
 * Provider 자동 변경 버튼 없음. EXTERNAL 실행 시 confirm 필수.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  App,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const DISCLAIMER =
  "벤치마크는 AI 품질 측정용입니다. 매매·주문·후보/전략과 무관합니다.";

export default function AdminAiBenchmarksPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [datasetId, setDatasetId] = useState<number>(1);
  const [mode, setMode] = useState("MOCK");
  const [providerCode, setProviderCode] = useState("mock");
  const [model, setModel] = useState("mock-v1");
  const [dryResult, setDryResult] = useState("");
  const [compareLeft, setCompareLeft] = useState<number | null>(null);
  const [compareResult, setCompareResult] = useState("");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiBenchmarks(),
    queryFn: () => adminApi.listAiBenchmarks(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const datasetsQuery = useQuery({
    queryKey: queryKeys.admin.aiEvaluationDatasets(),
    queryFn: () => adminApi.listAiEvaluationDatasets(),
  });
  const datasets = extractRows(asRecord(datasetsQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-benchmark", selectedId],
    queryFn: () => adminApi.getAiBenchmark(selectedId!),
    enabled: selectedId != null,
  });
  const benchmark = asRecord(asRecord(detailQuery.data)?.benchmark);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-benchmark-dashboard"],
    queryFn: adminApi.getAiBenchmarkDashboard,
  });
  const dash = asRecord(dashQuery.data);

  const scorecardsQuery = useQuery({
    queryKey: ["admin", "ai-scorecards"],
    queryFn: () => adminApi.getAiScorecards(),
  });
  const scorecards = extractRows(asRecord(scorecardsQuery.data)?.items);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.aiBenchmarks() });
    queryClient.invalidateQueries({ queryKey: ["admin", "ai-scorecards"] });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-benchmark", selectedId],
      });
    }
  };

  const requireReason = () => {
    if (!reason.trim()) {
      message.error("reason 필요");
      return false;
    }
    return true;
  };

  const createMut = useMutation({
    mutationFn: () =>
      adminApi.createAiBenchmark({
        reason,
        dataset_id: datasetId,
        provider_code: providerCode,
        model,
        execution_mode: mode,
      }),
    onSuccess: (data) => {
      message.success("벤치마크 생성 (MOCK 기본)");
      const id = asRecord(asRecord(data)?.benchmark)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const dryMut = useMutation({
    mutationFn: () => adminApi.dryRunAiBenchmark(selectedId!, { reason }),
    onSuccess: (data) => {
      setDryResult(JSON.stringify(data, null, 2));
      const called = asRecord(data)?.external_ai_called;
      message.success(
        called === false
          ? "Dry-run 완료 (external_ai_called=false)"
          : "Dry-run 완료",
      );
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const execMut = useMutation({
    mutationFn: (confirm: boolean) =>
      adminApi.executeAiBenchmark(selectedId!, { reason, confirm }),
    onSuccess: () => {
      message.success("벤치마크 실행 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const cancelMut = useMutation({
    mutationFn: () => adminApi.cancelAiBenchmark(selectedId!, { reason }),
    onSuccess: () => {
      message.success("취소");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const confirmExecute = () => {
    if (!requireReason() || selectedId == null) return;
    const isExternal = mode === "EXTERNAL";
    Modal.confirm({
      title: "벤치마크 실행",
      content: (
        <div>
          <p>{DISCLAIMER}</p>
          {isExternal ? (
            <p>
              EXTERNAL 모드: 외부 AI 호출이 발생합니다. confirm=true 필요.
            </p>
          ) : (
            <p>Mode={mode} — Mock/DRY_RUN은 외부 호출 없음.</p>
          )}
        </div>
      ),
      onOk: () => execMut.mutateAsync(isExternal),
    });
  };

  const runCompare = async () => {
    if (compareLeft == null || selectedId == null) {
      message.error("비교할 두 benchmark ID 필요");
      return;
    }
    try {
      const data = await adminApi.compareAiScorecards({
        left_benchmark_id: compareLeft,
        right_benchmark_id: selectedId,
      });
      setCompareResult(JSON.stringify(data, null, 2));
    } catch (e) {
      message.error(toApiError(e).message);
    }
  };

  const statusColor = (status: string) => {
    if (status === "COMPLETED") return "green";
    if (status === "FAILED") return "red";
    if (status === "RUNNING") return "processing";
    return "default";
  };

  return (
    <AdminPageShell
      title="Benchmark / Scorecard"
      description="평가 데이터셋 기반 AI 품질 벤치마크. MOCK 기본."
    >
      <Alert type="warning" showIcon title={DISCLAIMER} style={{ marginBottom: 16 }} />
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text>
            Today: {cell(dash?.benchmarks_today)} / Completed:{" "}
            {cell(dash?.completed)} / Failed: {cell(dash?.failed)}
          </Typography.Text>
        </Space>

        <Space wrap>
          <Input
            placeholder="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ width: 180 }}
          />
          <Select
            value={datasetId}
            onChange={setDatasetId}
            style={{ width: 200 }}
            options={datasets.map((d) => {
              const row = asRecord(d);
              return {
                value: row?.id as number,
                label: `${row?.code ?? row?.id}`,
              };
            })}
            placeholder="dataset_id"
          />
          <InputNumber
            value={datasetId}
            onChange={(v) => setDatasetId(v == null ? 1 : Number(v))}
            style={{ width: 100 }}
          />
          <Select
            value={mode}
            onChange={(v) => {
              setMode(v);
              if (v === "MOCK") {
                setProviderCode("mock");
                setModel("mock-v1");
              }
            }}
            options={[
              { value: "MOCK", label: "MOCK" },
              { value: "DRY_RUN", label: "DRY_RUN" },
              { value: "EXTERNAL", label: "EXTERNAL" },
            ]}
            style={{ width: 110 }}
          />
          <Input
            placeholder="provider_code"
            value={providerCode}
            onChange={(e) => setProviderCode(e.target.value)}
            style={{ width: 120 }}
          />
          <Input
            placeholder="model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            style={{ width: 120 }}
          />
          <Button
            type="primary"
            onClick={() => requireReason() && createMut.mutate()}
            loading={createMut.isPending}
          >
            벤치마크 생성
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && dryMut.mutate()}
            loading={dryMut.isPending}
          >
            Dry-run
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={confirmExecute}
            loading={execMut.isPending}
          >
            Execute
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && cancelMut.mutate()}
            loading={cancelMut.isPending}
          >
            Cancel
          </Button>
        </Space>

        <Table
          rowKey={(r) => String(asRecord(r)?.id ?? "")}
          loading={listQuery.isLoading}
          dataSource={items}
          pagination={{ pageSize: 10 }}
          onRow={(record) => ({
            onClick: () => {
              const id = asRecord(record)?.id;
              if (typeof id === "number") setSelectedId(id);
            },
          })}
          columns={[
            { title: "ID", dataIndex: "id", width: 70 },
            { title: "Dataset", dataIndex: "dataset_id", width: 80 },
            { title: "Mode", dataIndex: "execution_mode", width: 90 },
            { title: "Provider", dataIndex: "provider_code", width: 90 },
            { title: "Model", dataIndex: "model", width: 100 },
            {
              title: "상태",
              dataIndex: "benchmark_status",
              width: 120,
              render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
            },
            { title: "점수", dataIndex: "overall_score", width: 80 },
          ]}
        />

        {benchmark ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Title level={5}>상세 #{cell(benchmark.id)}</Typography.Title>
            <Typography.Text>
              Status={cell(benchmark.benchmark_status)} / Items=
              {cell(benchmark.processed_items)}/{cell(benchmark.total_items)}
            </Typography.Text>
            <pre style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(benchmark.scorecard ?? {}, null, 2)}
            </pre>
          </Space>
        ) : null}

        {dryResult ? (
          <pre style={{ whiteSpace: "pre-wrap", maxHeight: 200, overflow: "auto" }}>
            {dryResult}
          </pre>
        ) : null}

        <Typography.Title level={5}>Scorecards</Typography.Title>
        <Table
          rowKey={(r) => String(asRecord(r)?.benchmark_id ?? asRecord(r)?.id ?? "")}
          loading={scorecardsQuery.isLoading}
          dataSource={scorecards}
          pagination={{ pageSize: 5 }}
          size="small"
          columns={[
            { title: "Benchmark", dataIndex: "benchmark_id", width: 90 },
            { title: "Dataset", dataIndex: "dataset_id", width: 80 },
            { title: "Overall", dataIndex: "overall_score", width: 80 },
            { title: "Correctness", dataIndex: "correctness_score", width: 100 },
            { title: "Safety", dataIndex: "safety_score", width: 80 },
          ]}
        />

        <Space>
          <InputNumber
            placeholder="compare left benchmark id"
            value={compareLeft ?? undefined}
            onChange={(v) => setCompareLeft(v == null ? null : Number(v))}
          />
          <Button onClick={runCompare}>Scorecard Compare</Button>
        </Space>
        {compareResult ? (
          <pre style={{ whiteSpace: "pre-wrap" }}>{compareResult}</pre>
        ) : null}
      </Space>
    </AdminPageShell>
  );
}
