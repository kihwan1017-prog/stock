"use client";

/** STEP 11-4 — Output Schema 관리 (저장만으로 AI 호출 없음). */

import { useQuery } from "@tanstack/react-query";
import { Card, Space, Table, Tag, Typography } from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { queryKeys } from "@/lib/query/queryKeys";

export default function AdminAiSchemasPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiOutputSchemas(),
    queryFn: adminApi.listAiOutputSchemas,
  });
  const items = extractRows(asRecord(listQuery.data)?.items);
  const detailQuery = useQuery({
    queryKey: ["admin", "ai-output-schema", selectedId],
    queryFn: () => adminApi.getAiOutputSchema(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(detailQuery.data);

  return (
    <AdminPageShell
      title="AI Output Schema 관리"
      description="Structured Output Schema · 저장/조회로 외부 AI 호출 없음"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="Schema 목록" loading={listQuery.isLoading}>
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
              { title: "Version", dataIndex: "schema_version" },
              {
                title: "상태",
                dataIndex: "status",
                render: (v) => <Tag>{String(v)}</Tag>,
              },
              {
                title: "Checksum",
                dataIndex: "checksum",
                render: (v) => String(v ?? "").slice(0, 12),
              },
            ]}
          />
        </Card>
        {detail && (
          <Card size="small" title={`상세: ${cell(detail.code)}`}>
            <Typography.Paragraph type="secondary">
              Strict: {String(detail.strict_mode)} / additionalProperties:{" "}
              {String(detail.additional_properties_allowed)}
            </Typography.Paragraph>
            <pre style={{ maxHeight: 420, overflow: "auto" }}>
              {JSON.stringify(detail.json_schema ?? {}, null, 2)}
            </pre>
          </Card>
        )}
      </Space>
    </AdminPageShell>
  );
}
