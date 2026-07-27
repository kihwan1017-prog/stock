"use client";

/**
 * STEP 11-4 — Prompt Template / Version / Preview (외부 AI 호출 없음).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Input,
  Modal,
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

export default function AdminAiPromptsPage() {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [previewVars, setPreviewVars] = useState("{}");
  const [previewResult, setPreviewResult] = useState<string>("");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiPromptTemplates(),
    queryFn: adminApi.listAiPromptTemplates,
  });
  const items = extractRows(asRecord(listQuery.data)?.items);
  const selected = items.find((r) => Number(r.id) === selectedId) ?? null;

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-prompt-template", selectedId],
    queryFn: () => adminApi.getAiPromptTemplate(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(detailQuery.data);
  const versions = extractRows(detail?.versions);

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiPromptTemplates(),
    });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-prompt-template", selectedId],
      });
    }
  };

  const requireReason = () => {
    if (!reason.trim()) {
      message.error("변경 reason이 필요합니다");
      return false;
    }
    return true;
  };

  const activateMut = useMutation({
    mutationFn: (versionId: number) =>
      adminApi.activateAiPromptVersion(versionId, {
        reason,
        confirm: true,
      }),
    onSuccess: () => {
      message.success("Version 활성화됨 (AI 호출 없음)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell
      title="AI Prompt 관리"
      description="Template·Version·Preview · 외부 AI 호출 없음 · 전략/주문 연결 없음"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="변경 Reason (필수)">
          <Input.TextArea
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Card>

        <Card size="small" title="Prompt 목록" loading={listQuery.isLoading}>
          <Table
            size="small"
            rowKey="id"
            dataSource={items}
            pagination={false}
            onRow={(row) => ({
              onClick: () => setSelectedId(Number(row.id)),
            })}
            columns={[
              { title: "Code", dataIndex: "code" },
              { title: "Name", dataIndex: "name" },
              { title: "Task", dataIndex: "task_type" },
              {
                title: "Status",
                dataIndex: "status",
                render: (v) => <Tag>{String(v)}</Tag>,
              },
              { title: "Active Ver", dataIndex: "active_version_id" },
              { title: "Updated", dataIndex: "updated_at", ellipsis: true },
            ]}
          />
        </Card>

        {selected && (
          <Card size="small" title={`상세: ${cell(selected.code)}`}>
            <Typography.Paragraph type="secondary">
              Active Version: {cell(detail?.active_version_id) || "없음"} / Status:{" "}
              {cell(detail?.status)}
            </Typography.Paragraph>
            <Table
              size="small"
              rowKey="id"
              dataSource={versions}
              pagination={false}
              columns={[
                { title: "Ver", dataIndex: "version", width: 60 },
                { title: "Status", dataIndex: "status", width: 90 },
                {
                  title: "Checksum",
                  dataIndex: "checksum",
                  render: (v) => String(v ?? "").slice(0, 12),
                },
                {
                  title: "Action",
                  render: (_, row) => (
                    <Button
                      size="small"
                      disabled={String(row.status) === "ARCHIVED"}
                      onClick={() => {
                        if (!requireReason()) return;
                        Modal.confirm({
                          title: "Version 활성화",
                          content:
                            "활성화만 수행합니다. 외부 AI 호출/전략 생성 없음.",
                          onOk: () => activateMut.mutate(Number(row.id)),
                        });
                      }}
                    >
                      Activate
                    </Button>
                  ),
                },
              ]}
            />

            <Typography.Title level={5}>Preview (외부 AI 0)</Typography.Title>
            <Input.TextArea
              rows={4}
              value={previewVars}
              onChange={(e) => setPreviewVars(e.target.value)}
              placeholder='변수 JSON 예: {"symbol":"BTC","content":"..."}'
            />
            <Space style={{ marginTop: 8 }}>
              <Button
                onClick={async () => {
                  if (!requireReason()) return;
                  const active =
                    versions.find(
                      (v) => Number(v.id) === Number(detail?.active_version_id),
                    ) ?? versions[0];
                  if (!active) {
                    message.error("Version 없음");
                    return;
                  }
                  try {
                    const vars = JSON.parse(previewVars || "{}") as Record<
                      string,
                      unknown
                    >;
                    const data = await adminApi.previewAiPromptRender({
                      version_id: Number(active.id),
                      variables: vars,
                      reason,
                    });
                    setPreviewResult(JSON.stringify(data, null, 2));
                    message.success("Render Preview 완료 (AI 호출 없음)");
                  } catch (e) {
                    message.error(toApiError(e).message);
                  }
                }}
              >
                Render Preview
              </Button>
            </Space>
            {previewResult && (
              <Input.TextArea
                rows={12}
                value={previewResult}
                readOnly
                style={{ marginTop: 8, fontFamily: "monospace" }}
              />
            )}
          </Card>
        )}
      </Space>
    </AdminPageShell>
  );
}
