"use client";

/**
 * STEP 11-8 — AI 분석 품질 Human Review.
 * 매매 승인·주문·후보/전략 버튼 없음.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  App,
} from "antd";
import { useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const DISCLAIMER =
  "AI 분석 품질 승인입니다. 매매 승인이 아닙니다.";

const DECISION_OPTIONS = [
  { value: "APPROVED", label: "APPROVED (품질 승인)" },
  { value: "APPROVED_WITH_WARNINGS", label: "APPROVED_WITH_WARNINGS" },
  { value: "REVISION_REQUESTED", label: "REVISION_REQUESTED" },
  { value: "REJECTED", label: "REJECTED" },
];

const SCORE_FIELDS = [
  "correctness_score",
  "relevance_score",
  "completeness_score",
  "citation_score",
  "safety_score",
  "clarity_score",
] as const;

type ScoreField = (typeof SCORE_FIELDS)[number];

const defaultScores = (): Record<ScoreField, number> => ({
  correctness_score: 3,
  relevance_score: 3,
  completeness_score: 3,
  citation_score: 3,
  safety_score: 3,
  clarity_score: 3,
});

export default function AdminAiReviewsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [decision, setDecision] = useState("APPROVED");
  const [scores, setScores] = useState(defaultScores);
  const [findingsSummary, setFindingsSummary] = useState("");
  const [draftReviewId, setDraftReviewId] = useState<number | null>(null);

  const listQuery = useQuery({
    queryKey: [...queryKeys.admin.aiReviews(), statusFilter ?? "all"],
    queryFn: () =>
      adminApi.listAiReviewAssignments(
        statusFilter ? { status: statusFilter } : undefined,
      ),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-review-assignment", selectedId],
    queryFn: () => adminApi.getAiReviewAssignment(selectedId!),
    enabled: selectedId != null,
  });
  const assignment = asRecord(asRecord(detailQuery.data)?.assignment);

  const reviewsQuery = useQuery({
    queryKey: ["admin", "ai-review-assignment-reviews", selectedId],
    queryFn: () => adminApi.listAiReviewsForAssignment(selectedId!),
    enabled: selectedId != null,
  });
  const reviews = extractRows(asRecord(reviewsQuery.data)?.items);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-review-dashboard"],
    queryFn: adminApi.getAiReviewDashboard,
  });
  const dash = asRecord(dashQuery.data);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.aiReviews() });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-review-assignment", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-review-assignment-reviews", selectedId],
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

  const draftMut = useMutation({
    mutationFn: () =>
      adminApi.createAiReviewDraft(selectedId!, {
        reason,
        decision,
        findings_summary: findingsSummary || undefined,
        ...scores,
      }),
    onSuccess: (data) => {
      message.success("AI 분석 품질 검토 초안 저장");
      const id = asRecord(asRecord(data)?.review)?.id;
      if (typeof id === "number") setDraftReviewId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const submitMut = useMutation({
    mutationFn: (reviewId: number) =>
      adminApi.submitAiReview(reviewId, { reason }),
    onSuccess: () => {
      message.success("AI 분석 품질 승인 제출 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const cancelMut = useMutation({
    mutationFn: () =>
      adminApi.cancelAiReviewAssignment(selectedId!, { reason }),
    onSuccess: () => {
      message.success("할당 취소");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const handleSaveAndSubmit = async () => {
    if (!requireReason() || selectedId == null) return;
    try {
      const draft = await draftMut.mutateAsync();
      const reviewId = asRecord(asRecord(draft)?.review)?.id;
      if (typeof reviewId === "number") {
        await submitMut.mutateAsync(reviewId);
      }
    } catch {
      // mutation onError에서 처리
    }
  };

  const decisionColor = (value: string) => {
    if (value === "APPROVED" || value === "APPROVED_WITH_WARNINGS") return "green";
    if (value === "REJECTED") return "red";
    if (value === "PENDING") return "gold";
    return "default";
  };

  return (
    <AdminPageShell
      title="Human Review"
      description="AI 분석 품질 검토 인박스. 매매·주문·후보/전략과 무관합니다."
    >
      <Alert type="warning" showIcon title={DISCLAIMER} style={{ marginBottom: 16 }} />
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text>
            Pending: {cell(dash?.pending_assignments)} / In Review:{" "}
            {cell(dash?.in_review)} / Completed: {cell(dash?.completed_today)}
          </Typography.Text>
          <Select
            allowClear
            placeholder="status filter"
            value={statusFilter}
            onChange={setStatusFilter}
            options={[
              { value: "ASSIGNED", label: "ASSIGNED" },
              { value: "IN_REVIEW", label: "IN_REVIEW" },
              { value: "COMPLETED", label: "COMPLETED" },
              { value: "CANCELLED", label: "CANCELLED" },
            ]}
            style={{ width: 140 }}
          />
          <Input
            placeholder="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ width: 200 }}
          />
        </Space>

        <Table
          rowKey={(r) => String(asRecord(r)?.id ?? "")}
          loading={listQuery.isLoading}
          dataSource={items}
          pagination={{ pageSize: 10 }}
          onRow={(record) => ({
            onClick: () => {
              const id = asRecord(record)?.id;
              if (typeof id === "number") {
                setSelectedId(id);
                setDraftReviewId(null);
              }
            },
          })}
          columns={[
            { title: "ID", dataIndex: "id", width: 70 },
            { title: "Source", dataIndex: "analysis_source_type", width: 100 },
            { title: "Analysis ID", dataIndex: "source_analysis_id", width: 110 },
            { title: "Status", dataIndex: "status", width: 120 },
            { title: "Priority", dataIndex: "priority", width: 90 },
            { title: "Reviewer", dataIndex: "assigned_reviewer_id", ellipsis: true },
            {
              title: "Decision",
              dataIndex: "current_decision",
              width: 160,
              render: (v: string) =>
                v ? <Tag color={decisionColor(v)}>{v}</Tag> : "-",
            },
          ]}
        />

        {assignment ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Title level={5}>
              할당 상세 #{cell(assignment.id)}
            </Typography.Title>
            <Typography.Paragraph type="secondary">{DISCLAIMER}</Typography.Paragraph>
            <Typography.Text>
              Source={cell(assignment.analysis_source_type)} / Analysis=
              {cell(assignment.source_analysis_id)} / Status={cell(assignment.status)}
            </Typography.Text>

            <Typography.Title level={5}>점수 (0–5)</Typography.Title>
            <Space wrap>
              {SCORE_FIELDS.map((field) => (
                <Space key={field} orientation="vertical" size={0}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {field.replace("_score", "")}
                  </Typography.Text>
                  <InputNumber
                    min={0}
                    max={5}
                    step={0.5}
                    value={scores[field]}
                    onChange={(v) =>
                      setScores((prev) => ({
                        ...prev,
                        [field]: v == null ? 0 : Number(v),
                      }))
                    }
                    style={{ width: 110 }}
                  />
                </Space>
              ))}
            </Space>

            <Space wrap>
              <Select
                value={decision}
                onChange={setDecision}
                options={DECISION_OPTIONS}
                style={{ width: 260 }}
              />
              <Input.TextArea
                placeholder="findings_summary"
                value={findingsSummary}
                onChange={(e) => setFindingsSummary(e.target.value)}
                rows={2}
                style={{ width: 360 }}
              />
            </Space>

            <Space>
              <Button
                type="primary"
                onClick={() => requireReason() && draftMut.mutate()}
                loading={draftMut.isPending}
              >
                초안 저장
              </Button>
              <Button
                onClick={handleSaveAndSubmit}
                loading={draftMut.isPending || submitMut.isPending}
              >
                저장 후 AI 분석 품질 승인 제출
              </Button>
              {draftReviewId != null ? (
                <Button
                  onClick={() => requireReason() && submitMut.mutate(draftReviewId)}
                  loading={submitMut.isPending}
                >
                  제출 (초안 #{draftReviewId})
                </Button>
              ) : null}
              <Button
                danger
                onClick={() => requireReason() && cancelMut.mutate()}
                loading={cancelMut.isPending}
              >
                할당 취소
              </Button>
            </Space>

            {reviews.length > 0 ? (
              <>
                <Typography.Title level={5}>검토 이력</Typography.Title>
                <Table
                  rowKey={(r) => String(asRecord(r)?.id ?? "")}
                  dataSource={reviews}
                  pagination={false}
                  size="small"
                  columns={[
                    { title: "ID", dataIndex: "id", width: 60 },
                    { title: "Status", dataIndex: "review_status", width: 100 },
                    {
                      title: "Decision",
                      dataIndex: "decision",
                      render: (v: string) => (
                        <Tag color={decisionColor(v)}>{v}</Tag>
                      ),
                    },
                    { title: "Overall", dataIndex: "overall_score", width: 80 },
                    { title: "Safety", dataIndex: "safety_score", width: 70 },
                  ]}
                />
              </>
            ) : null}
          </Space>
        ) : null}

        <Typography.Link href={adminRoutes.aiDocumentAnalyses}>
          문서 분석 →
        </Typography.Link>
      </Space>
    </AdminPageShell>
  );
}
