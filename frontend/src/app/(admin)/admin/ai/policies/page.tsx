"use client";

/** STEP 11-4 — Policy 관리 (Core Safety는 코드 강제, DB로 해제 불가). */

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

export default function AdminAiPoliciesPage() {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiPolicies(),
    queryFn: adminApi.listAiPolicies,
  });
  const items = extractRows(asRecord(listQuery.data)?.items);
  const detailQuery = useQuery({
    queryKey: ["admin", "ai-policy", selectedId],
    queryFn: () => adminApi.getAiPolicy(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(detailQuery.data);

  const activateMut = useMutation({
    mutationFn: () =>
      adminApi.activateAiPolicy(selectedId!, { reason, confirm: true }),
    onSuccess: () => {
      message.success("Policy 활성화됨 (AI 호출 없음)");
      queryClient.invalidateQueries({
        queryKey: queryKeys.admin.aiPolicies(),
      });
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  return (
    <AdminPageShell
      title="AI Policy 관리"
      description="DB Policy + Core Safety(코드 강제) · 주문/LIVE/ARM 금지는 해제 불가"
    >
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small" title="변경 Reason (필수)">
          <Input.TextArea
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Card>
        <Card size="small" title="Policy 목록" loading={listQuery.isLoading}>
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
              { title: "Type", dataIndex: "policy_type" },
              { title: "Ver", dataIndex: "version", width: 60 },
              {
                title: "Status",
                dataIndex: "status",
                render: (v) => <Tag>{String(v)}</Tag>,
              },
              {
                title: "Core",
                dataIndex: "is_core",
                render: (v) => (v ? <Tag color="red">CORE</Tag> : "—"),
              },
              { title: "Mode", dataIndex: "enforcement_mode" },
            ]}
          />
        </Card>
        {detail && (
          <Card size="small" title={`상세: ${cell(detail.code)}`}>
            <Typography.Paragraph>
              {detail.is_core
                ? "핵심 Policy — 비활성화 대신 신규 Version 활성화만 허용"
                : "일반 Policy"}
            </Typography.Paragraph>
            <pre style={{ maxHeight: 320, overflow: "auto" }}>
              {JSON.stringify(detail.rules ?? {}, null, 2)}
            </pre>
            <Button
              type="primary"
              onClick={() => {
                if (!reason.trim()) {
                  message.error("reason 필요");
                  return;
                }
                Modal.confirm({
                  title: "Policy 활성화",
                  content: "동일 code의 다른 ACTIVE는 INACTIVE로 전환됩니다.",
                  onOk: () => activateMut.mutate(),
                });
              }}
            >
              Activate
            </Button>
          </Card>
        )}
      </Space>
    </AdminPageShell>
  );
}
