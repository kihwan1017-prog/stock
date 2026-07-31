"use client";

/**
 * STEP 12-1 — AI Candidate -> Strategy Request 승인 게이트 (관리자 심사).
 * 승인은 "사람이 근거를 확인했다"는 의미이며, Strategy Draft 생성·
 * Backtest·실거래 승인·Runtime 등록을 의미하지 않는다(STEP12-2 이후).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const STATUS_COLOR: Record<string, string> = {
  PENDING_REVIEW: "processing",
  APPROVED: "success",
  REJECTED: "error",
  CANCELLED: "default",
  EXPIRED: "warning",
};

const STATUS_OPTIONS = [
  { value: "", label: "전체" },
  { value: "PENDING_REVIEW", label: "PENDING_REVIEW" },
  { value: "APPROVED", label: "APPROVED" },
  { value: "REJECTED", label: "REJECTED" },
  { value: "CANCELLED", label: "CANCELLED" },
  { value: "EXPIRED", label: "EXPIRED" },
];

export default function AdminStrategyRequestsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [statusFilter, setStatusFilter] = useState("PENDING_REVIEW");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [reviewNote, setReviewNote] = useState("");

  const listParams = { status: statusFilter || undefined, limit: 50 };
  const listQuery = useQuery({
    queryKey: queryKeys.admin.strategyRequests.list(listParams),
    queryFn: () => adminApi.listStrategyRequests(listParams),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: queryKeys.admin.strategyRequests.detail(selectedId ?? 0),
    queryFn: () => adminApi.getStrategyRequest(selectedId as number),
    enabled: selectedId != null,
  });
  const detail = asRecord(detailQuery.data) ?? {};

  const historyQuery = useQuery({
    queryKey: queryKeys.admin.strategyRequests.history(selectedId ?? 0),
    queryFn: () => adminApi.getStrategyRequestHistory(selectedId as number),
    enabled: selectedId != null,
  });
  const historyItems = extractRows(asRecord(historyQuery.data)?.items);

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "strategy-requests"],
    });
  };

  const approveMutation = useMutation({
    mutationFn: (id: number) =>
      adminApi.approveStrategyRequest(id, {
        review_note: reviewNote.trim() || undefined,
      }),
    onSuccess: async () => {
      message.success("승인되었습니다.");
      setReviewNote("");
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: number) => {
      if (!reviewNote.trim()) {
        throw new Error("반려 사유(review_note)가 필요합니다.");
      }
      return adminApi.rejectStrategyRequest(id, {
        review_note: reviewNote.trim(),
      });
    },
    onSuccess: async () => {
      message.success("반려되었습니다.");
      setReviewNote("");
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const isPending = detail.status === "PENDING_REVIEW";

  return (
    <AdminPageShell title="Strategy Request 심사">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="이 화면의 승인/반려는 사람의 근거 확인 결과이며, Strategy Draft 생성·Backtest·실거래 승인을 의미하지 않습니다."
        />

        <Space wrap>
          <Select
            style={{ width: 200 }}
            value={statusFilter}
            onChange={setStatusFilter}
            options={STATUS_OPTIONS}
          />
          <Typography.Link href="/admin/ai/candidate-lifecycle">
            Candidate Lifecycle
          </Typography.Link>
        </Space>

        <Table
          size="small"
          loading={listQuery.isLoading}
          dataSource={items}
          rowKey={(r) => String(asRecord(r)?.strategy_request_id)}
          pagination={{ pageSize: 10 }}
          onRow={(r) => ({
            onClick: () => {
              const id = asRecord(r)?.strategy_request_id;
              if (typeof id === "number") setSelectedId(id);
            },
          })}
          columns={[
            { title: "ID", dataIndex: "strategy_request_id", width: 70, render: cell },
            { title: "Candidate", dataIndex: "candidate_id", width: 100, render: cell },
            { title: "User", dataIndex: "user_id", width: 90, render: cell },
            {
              title: "상태",
              dataIndex: "status",
              width: 140,
              render: (v: string) => (
                <Tag color={STATUS_COLOR[v] ?? "default"}>{v}</Tag>
              ),
            },
            {
              title: "요청 시점 Candidate 상태",
              dataIndex: "candidate_lifecycle_status_snapshot",
              render: cell,
            },
            { title: "요청일시", dataIndex: "requested_at", render: cell },
          ]}
        />

        {listQuery.isError && (
          <Alert type="error" title={toApiError(listQuery.error).message} />
        )}
      </Space>

      <Drawer
        title={
          selectedId != null
            ? `Strategy Request #${selectedId}`
            : "상세"
        }
        open={selectedId != null}
        onClose={() => setSelectedId(null)}
        size={560}
        destroyOnHidden
      >
        {detailQuery.isLoading ? (
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        ) : (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={STATUS_COLOR[String(detail.status)] ?? "default"}>
                {cell(detail.status)}
              </Tag>
              <Tag>Candidate #{cell(detail.candidate_id)}</Tag>
            </Space>

            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="요청자 user_id">
                {cell(detail.user_id)}
              </Descriptions.Item>
              <Descriptions.Item label="심사자 reviewer_user_id">
                {cell(detail.reviewer_user_id)}
              </Descriptions.Item>
              <Descriptions.Item label="요청 시점 Candidate 상태(근거)">
                {cell(detail.candidate_lifecycle_status_snapshot)}
              </Descriptions.Item>
              <Descriptions.Item label="요청 사유">
                {cell(detail.request_note)}
              </Descriptions.Item>
              <Descriptions.Item label="심사 의견">
                {cell(detail.review_note)}
              </Descriptions.Item>
              <Descriptions.Item label="요청일시">
                {cell(detail.requested_at)}
              </Descriptions.Item>
              <Descriptions.Item label="심사일시">
                {cell(detail.reviewed_at)}
              </Descriptions.Item>
            </Descriptions>

            {isPending && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Input.TextArea
                  rows={3}
                  placeholder="심사 의견(반려 시 필수)"
                  value={reviewNote}
                  onChange={(e) => setReviewNote(e.target.value)}
                  maxLength={1000}
                />
                <Space>
                  <Button
                    type="primary"
                    loading={approveMutation.isPending}
                    onClick={() =>
                      selectedId != null &&
                      approveMutation.mutate(selectedId)
                    }
                  >
                    승인
                  </Button>
                  <Button
                    danger
                    loading={rejectMutation.isPending}
                    onClick={() =>
                      selectedId != null && rejectMutation.mutate(selectedId)
                    }
                  >
                    반려
                  </Button>
                </Space>
              </Space>
            )}

            <Typography.Title level={5}>History</Typography.Title>
            {historyItems.length === 0 ? (
              <Empty description="이력 없음" />
            ) : (
              <Table
                size="small"
                dataSource={historyItems}
                rowKey={(r) => String(asRecord(r)?.history_id)}
                pagination={false}
                columns={[
                  { title: "Action", dataIndex: "action", render: cell },
                  { title: "From", dataIndex: "previous_status", render: cell },
                  { title: "To", dataIndex: "new_status", render: cell },
                  { title: "Actor", dataIndex: "actor", render: cell },
                  { title: "At", dataIndex: "created_at", render: cell },
                ]}
              />
            )}
          </Space>
        )}
      </Drawer>
    </AdminPageShell>
  );
}
