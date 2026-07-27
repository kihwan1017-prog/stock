"use client";

/**
 * STEP 11-8 — AI 평가 데이터셋 관리.
 * 승인된 분석 일괄 추가 버튼 없음.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const DISCLAIMER =
  "평가 데이터셋은 AI 품질 벤치마크용입니다. 매매·주문 데이터가 아닙니다.";

export default function AdminAiEvaluationDatasetsPage() {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [taskType, setTaskType] = useState("NEWS_ANALYSIS");
  const [inputHash, setInputHash] = useState("");
  const [expectedJson, setExpectedJson] = useState("{}");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiEvaluationDatasets(),
    queryFn: () => adminApi.listAiEvaluationDatasets(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-evaluation-dataset", selectedId],
    queryFn: () => adminApi.getAiEvaluationDataset(selectedId!),
    enabled: selectedId != null,
  });
  const dataset = asRecord(asRecord(detailQuery.data)?.dataset);
  const datasetItems = extractRows(asRecord(dataset)?.items);

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiEvaluationDatasets(),
    });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-evaluation-dataset", selectedId],
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
      adminApi.createAiEvaluationDataset({
        reason,
        code,
        name,
        task_type: taskType,
        description: "",
      }),
    onSuccess: (data) => {
      message.success("데이터셋 생성");
      const id = asRecord(asRecord(data)?.dataset)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const addItemMut = useMutation({
    mutationFn: () => {
      let expectedResult: unknown = {};
      try {
        expectedResult = JSON.parse(expectedJson || "{}");
      } catch {
        throw new Error("expected_result JSON 형식 오류");
      }
      return adminApi.addAiEvaluationDatasetItem(selectedId!, {
        reason,
        input_reference_hash: inputHash || undefined,
        expected_result: expectedResult,
      });
    },
    onSuccess: () => {
      message.success("항목 추가");
      setInputHash("");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const validateMut = useMutation({
    mutationFn: () =>
      adminApi.validateAiEvaluationDataset(selectedId!, { reason }),
    onSuccess: () => {
      message.success("검증 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const activateMut = useMutation({
    mutationFn: () =>
      adminApi.activateAiEvaluationDataset(selectedId!, { reason }),
    onSuccess: () => {
      message.success("활성화");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const archiveMut = useMutation({
    mutationFn: () =>
      adminApi.archiveAiEvaluationDataset(selectedId!, { reason }),
    onSuccess: () => {
      message.success("보관");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const statusColor = (status: string) => {
    if (status === "ACTIVE") return "green";
    if (status === "DRAFT") return "blue";
    if (status === "ARCHIVED") return "default";
    return "gold";
  };

  return (
    <AdminPageShell
      title="Evaluation Dataset"
      description="AI 품질 평가용 골든 데이터셋 관리"
    >
      <Alert type="info" showIcon title={DISCLAIMER} style={{ marginBottom: 16 }} />
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap>
          <Input
            placeholder="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ width: 180 }}
          />
          <Input
            placeholder="code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            style={{ width: 140 }}
          />
          <Input
            placeholder="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ width: 180 }}
          />
          <Select
            value={taskType}
            onChange={setTaskType}
            options={[
              { value: "NEWS_ANALYSIS", label: "NEWS_ANALYSIS" },
              { value: "CHART_ANALYSIS", label: "CHART_ANALYSIS" },
              { value: "MARKET_ANALYSIS", label: "MARKET_ANALYSIS" },
            ]}
            style={{ width: 160 }}
          />
          <Button
            type="primary"
            onClick={() => requireReason() && code && name && createMut.mutate()}
            loading={createMut.isPending}
          >
            데이터셋 생성
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
            { title: "Code", dataIndex: "code", width: 140 },
            { title: "Name", dataIndex: "name", ellipsis: true },
            { title: "Task", dataIndex: "task_type", width: 140 },
            {
              title: "Status",
              dataIndex: "status",
              width: 110,
              render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag>,
            },
            { title: "Items", dataIndex: "item_count", width: 80 },
          ]}
        />

        {dataset ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Title level={5}>
              상세 #{cell(dataset.id)} — {cell(dataset.code)}
            </Typography.Title>
            <Typography.Text>
              Status={cell(dataset.status)} / Items={cell(dataset.item_count)} /
              Validated={cell(dataset.validation_status)}
            </Typography.Text>

            <Space wrap>
              <Button
                onClick={() => requireReason() && validateMut.mutate()}
                loading={validateMut.isPending}
              >
                Validate
              </Button>
              <Button
                type="primary"
                onClick={() => requireReason() && activateMut.mutate()}
                loading={activateMut.isPending}
              >
                Activate
              </Button>
              <Button
                danger
                onClick={() => requireReason() && archiveMut.mutate()}
                loading={archiveMut.isPending}
              >
                Archive
              </Button>
            </Space>

            <Typography.Title level={5}>항목 추가</Typography.Title>
            <Space orientation="vertical" style={{ width: "100%" }}>
              <Input
                placeholder="input_reference_hash"
                value={inputHash}
                onChange={(e) => setInputHash(e.target.value)}
              />
              <Input.TextArea
                placeholder='expected_result JSON (예: {"sentiment":"POSITIVE"})'
                value={expectedJson}
                onChange={(e) => setExpectedJson(e.target.value)}
                rows={4}
              />
              <Button
                onClick={() => requireReason() && addItemMut.mutate()}
                loading={addItemMut.isPending}
              >
                항목 추가
              </Button>
            </Space>

            {datasetItems.length > 0 ? (
              <Table
                rowKey={(r) => String(asRecord(r)?.id ?? "")}
                dataSource={datasetItems}
                pagination={{ pageSize: 5 }}
                size="small"
                columns={[
                  { title: "ID", dataIndex: "id", width: 60 },
                  {
                    title: "Hash",
                    dataIndex: "input_reference_hash",
                    ellipsis: true,
                  },
                  {
                    title: "Classification",
                    dataIndex: "data_classification",
                    width: 120,
                  },
                ]}
              />
            ) : null}
          </Space>
        ) : null}
      </Space>
    </AdminPageShell>
  );
}
