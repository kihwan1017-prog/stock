"use client";

/**
 * STEP 11-5 — AI Execution 관리.
 * create ≠ execute. DRY_RUN 외부 호출 0. MOCK 기본. EXTERNAL은 confirm 필수.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
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

export default function AdminAiExecutionsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [taskType, setTaskType] = useState("CHAT");
  const [mode, setMode] = useState("MOCK");
  const [inputJson, setInputJson] = useState('{"text":"Hello summary test"}');
  const [maxTokens, setMaxTokens] = useState(64);
  const [dryResult, setDryResult] = useState("");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiExecutions(),
    queryFn: adminApi.listAiExecutions,
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-execution", selectedId],
    queryFn: () => adminApi.getAiExecution(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(detailQuery.data);
  const request = asRecord(detail?.request);
  const runs = extractRows(detail?.runs);
  const events = extractRows(detail?.events);
  const result = asRecord(detail?.result);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.aiExecutions() });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-execution", selectedId],
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
    mutationFn: async () => {
      const payload = JSON.parse(inputJson || "{}") as Record<string, unknown>;
      return adminApi.createAiExecution({
        reason,
        idempotency_key: `fe-${Date.now()}`,
        task_type: taskType,
        execution_mode: mode,
        input_payload: payload,
        provider_code: mode === "MOCK" ? "mock" : undefined,
        max_tokens: maxTokens,
      });
    },
    onSuccess: (data) => {
      message.success("Request 생성됨 (자동 실행 없음)");
      const id = Number(asRecord(asRecord(data)?.request)?.id);
      if (id) setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell
      title="AI Execution 관리"
      description="CHAT/SUMMARIZE만 · create≠execute · DRY_RUN 외부호출 0 · 전략/주문 연결 없음"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="Reason (필수)">
          <Input.TextArea
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Card>

        <Card size="small" title="Execution 생성">
          <Space wrap>
            <Select
              value={taskType}
              style={{ width: 180 }}
              onChange={setTaskType}
              options={[
                { value: "CHAT", label: "CHAT" },
                { value: "SUMMARIZE", label: "SUMMARIZE" },
              ]}
            />
            <Select
              value={mode}
              style={{ width: 140 }}
              onChange={setMode}
              options={[
                { value: "DRY_RUN", label: "DRY_RUN" },
                { value: "MOCK", label: "MOCK" },
                { value: "EXTERNAL", label: "EXTERNAL" },
              ]}
            />
            <InputNumber
              min={8}
              max={4096}
              value={maxTokens}
              onChange={(v) => setMaxTokens(Number(v || 64))}
            />
          </Space>
          <Input.TextArea
            rows={4}
            style={{ marginTop: 8 }}
            value={inputJson}
            onChange={(e) => setInputJson(e.target.value)}
          />
          <Button
            type="primary"
            style={{ marginTop: 8 }}
            loading={createMut.isPending}
            onClick={() => {
              if (!requireReason()) return;
              createMut.mutate();
            }}
          >
            Create Request
          </Button>
        </Card>

        <Card size="small" title="목록" loading={listQuery.isLoading}>
          <Table
            size="small"
            rowKey="id"
            dataSource={items}
            pagination={false}
            onRow={(row) => ({
              onClick: () => setSelectedId(Number(row.id)),
            })}
            columns={[
              { title: "ID", dataIndex: "id", width: 70 },
              { title: "Task", dataIndex: "task_type", width: 110 },
              { title: "Mode", dataIndex: "execution_mode", width: 90 },
              {
                title: "Status",
                dataIndex: "status",
                render: (v) => <Tag>{String(v)}</Tag>,
              },
              { title: "Provider", dataIndex: "provider_code" },
              { title: "By", dataIndex: "requested_by", ellipsis: true },
              { title: "Created", dataIndex: "created_at", ellipsis: true },
            ]}
          />
        </Card>

        {selectedId != null && request && (
          <Card size="small" title={`상세 #${selectedId}`}>
            <Typography.Paragraph type="secondary">
              Status: {cell(request.status)} / Mode: {cell(request.execution_mode)} /
              Hash: {cell(request.input_hash)?.slice(0, 12)}
            </Typography.Paragraph>
            <Space wrap>
              <Button
                onClick={async () => {
                  if (!requireReason()) return;
                  try {
                    const data = await adminApi.dryRunAiExecution(selectedId, {
                      reason,
                    });
                    setDryResult(JSON.stringify(data, null, 2));
                    message.success("Dry-run 완료 (외부 호출 0)");
                    invalidate();
                  } catch (e) {
                    message.error(toApiError(e).message);
                  }
                }}
              >
                Dry-run
              </Button>
              <Button
                type="primary"
                onClick={() => {
                  if (!requireReason()) return;
                  Modal.confirm({
                    title: "Execute 확인",
                    content: (
                      <div>
                        <div>Mode: {cell(request.execution_mode)}</div>
                        <div>Provider: {cell(request.provider_code)}</div>
                        <div>Max Tokens: {cell(request.max_tokens)}</div>
                        <div>
                          EXTERNAL이면 실제 비용이 발생할 수 있습니다. Cancel은
                          환불을 보장하지 않습니다.
                        </div>
                      </div>
                    ),
                    onOk: async () => {
                      try {
                        await adminApi.executeAiExecution(selectedId, {
                          reason,
                          confirm: true,
                          expected_version: request.lock_version,
                        });
                        message.success("Execute 완료");
                        invalidate();
                      } catch (e) {
                        message.error(toApiError(e).message);
                      }
                    },
                  });
                }}
              >
                Execute
              </Button>
              <Button
                danger
                onClick={() => {
                  if (!requireReason()) return;
                  Modal.confirm({
                    title: "Cancel",
                    content: "취소해도 이미 발생한 Provider 비용은 환불되지 않을 수 있습니다.",
                    onOk: async () => {
                      try {
                        await adminApi.cancelAiExecution(selectedId, {
                          reason,
                          expected_version: request.lock_version,
                        });
                        message.success("Cancel 요청됨");
                        invalidate();
                      } catch (e) {
                        message.error(toApiError(e).message);
                      }
                    },
                  });
                }}
              >
                Cancel
              </Button>
            </Space>

            {dryResult && (
              <Input.TextArea
                rows={8}
                readOnly
                value={dryResult}
                style={{ marginTop: 8, fontFamily: "monospace" }}
              />
            )}

            <Typography.Title level={5}>Runs</Typography.Title>
            <Table
              size="small"
              rowKey="id"
              dataSource={runs}
              pagination={false}
              columns={[
                { title: "#", dataIndex: "attempt_no", width: 50 },
                { title: "Provider", dataIndex: "provider_code" },
                { title: "Status", dataIndex: "status" },
                { title: "Tokens", dataIndex: "total_tokens" },
                { title: "Cost", dataIndex: "estimated_cost" },
                { title: "Latency", dataIndex: "latency_ms" },
                { title: "Error", dataIndex: "error_code" },
              ]}
            />

            <Typography.Title level={5}>Safe Result</Typography.Title>
            <pre style={{ maxHeight: 240, overflow: "auto" }}>
              {JSON.stringify(result ?? {}, null, 2)}
            </pre>

            <Typography.Title level={5}>Events</Typography.Title>
            <Table
              size="small"
              rowKey="id"
              dataSource={events}
              pagination={false}
              columns={[
                { title: "Event", dataIndex: "event_type" },
                { title: "From", dataIndex: "previous_status", width: 100 },
                { title: "To", dataIndex: "new_status", width: 100 },
                { title: "At", dataIndex: "created_at", ellipsis: true },
              ]}
            />
          </Card>
        )}
      </Space>
    </AdminPageShell>
  );
}
