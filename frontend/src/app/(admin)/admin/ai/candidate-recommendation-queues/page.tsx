"use client";

/**
 * STEP 11-11 — AI 후보 추천 검토 큐.
 * APPROVED_FOR_CONSIDERATION = 기존 후보 등록 검토 가능 (후보 INSERT·매매 아님).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const REFERENCE_DISCLAIMER =
  "AI 후보 추천 검토 큐는 기존 Candidate 등록 여부를 검토하기 위한 내부 업무 큐이며, " +
  "실제 매수·매도 추천이나 주문 승인이 아닙니다.";
const CONSIDERATION_LABEL = "기존 후보 등록 검토 가능";

const DECISION_OPTIONS = [
  { value: "APPROVED_FOR_CONSIDERATION", label: CONSIDERATION_LABEL },
  { value: "APPROVED_WITH_WARNINGS", label: "경고 조건부 후보 등록 검토 가능" },
  { value: "REJECTED", label: "REJECTED" },
  { value: "MORE_INFORMATION_REQUIRED", label: "MORE_INFORMATION_REQUIRED" },
  { value: "ON_HOLD", label: "ON_HOLD" },
];

const DEFAULT_RUBRIC = {
  eligibility_score: 4,
  analytical_quality_score: 4,
  evidence_quality_score: 4,
  risk_awareness_score: 4,
  consistency_score: 4,
  safety_score: 4,
};

export default function AdminAiCandidateRecommendationQueuesPage() {
  // static message API는 테마 컨텍스트를 못 씀 → App.useApp 사용
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [sourceType, setSourceType] = useState("CANDIDATE_ASSESSMENT");
  const [assessmentId, setAssessmentId] = useState<number | null>(1);
  const [consensusId, setConsensusId] = useState<number | null>(null);
  const [priority, setPriority] = useState("NORMAL");
  const [assigneeId, setAssigneeId] = useState("reviewer-1");
  const [reviewerId, setReviewerId] = useState("reviewer-1");
  const [activeReviewId, setActiveReviewId] = useState<number | null>(null);
  const [decision, setDecision] = useState("APPROVED_FOR_CONSIDERATION");
  const [managerOverride, setManagerOverride] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [validateResult, setValidateResult] = useState("");
  const [compareLeft, setCompareLeft] = useState<number | null>(null);
  const [compareResult, setCompareResult] = useState("");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiCandidateRecommendationQueues(),
    queryFn: () => adminApi.listAiCandidateRecommendationQueues(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-candidate-recommendation-queue", selectedId],
    queryFn: () => adminApi.getAiCandidateRecommendationQueue(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(asRecord(detailQuery.data)?.queue);

  const reviewsQuery = useQuery({
    queryKey: ["admin", "ai-candidate-recommendation-queue-reviews", selectedId],
    queryFn: () => adminApi.getAiCandidateRecommendationQueueReviews(selectedId!),
    enabled: selectedId != null,
  });
  const reviewItems = extractRows(asRecord(reviewsQuery.data)?.items);

  const findingsQuery = useQuery({
    queryKey: ["admin", "ai-candidate-recommendation-queue-findings", selectedId],
    queryFn: () => adminApi.getAiCandidateRecommendationQueueFindings(selectedId!),
    enabled: selectedId != null,
  });
  const findingItems = extractRows(asRecord(findingsQuery.data)?.items);

  const decisionsQuery = useQuery({
    queryKey: ["admin", "ai-candidate-recommendation-queue-decisions", selectedId],
    queryFn: () => adminApi.getAiCandidateRecommendationQueueDecisions(selectedId!),
    enabled: selectedId != null,
  });
  const decisionItems = extractRows(asRecord(decisionsQuery.data)?.items);

  const historyQuery = useQuery({
    queryKey: ["admin", "ai-candidate-recommendation-queue-history", selectedId],
    queryFn: () => adminApi.getAiCandidateRecommendationQueueHistory(selectedId!),
    enabled: selectedId != null,
  });
  const historyItems = extractRows(asRecord(historyQuery.data)?.items);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-candidate-recommendation-queue-dashboard"],
    queryFn: adminApi.getAiCandidateRecommendationQueueDashboard,
  });
  const dash = asRecord(dashQuery.data) ?? {};
  const statusCounts = asRecord(dash.status_counts) ?? {};

  const latestDraftReview = useMemo(() => {
    for (let i = reviewItems.length - 1; i >= 0; i -= 1) {
      const row = asRecord(reviewItems[i]);
      if (row?.review_status === "DRAFT" && typeof row.id === "number") {
        return row.id as number;
      }
    }
    return activeReviewId;
  }, [reviewItems, activeReviewId]);

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiCandidateRecommendationQueues(),
    });
    queryClient.invalidateQueries({
      queryKey: ["admin", "ai-candidate-recommendation-queue-dashboard"],
    });
    if (selectedId != null) {
      for (const suffix of [
        "",
        "-reviews",
        "-findings",
        "-decisions",
        "-history",
      ]) {
        queryClient.invalidateQueries({
          queryKey: ["admin", "ai-candidate-recommendation-queue" + suffix, selectedId],
        });
      }
    }
  };

  const requireReason = () => {
    if (!reason.trim()) {
      message.error("reason 필요");
      return false;
    }
    return true;
  };

  const validateMut = useMutation({
    mutationFn: () =>
      adminApi.validateAiCandidateRecommendationQueue({
        source_type: sourceType,
        candidate_assessment_id:
          sourceType === "CANDIDATE_ASSESSMENT" ? assessmentId ?? undefined : undefined,
        candidate_consensus_id:
          sourceType === "CANDIDATE_CONSENSUS" ? consensusId ?? undefined : undefined,
      }),
    onSuccess: (data) => {
      setValidateResult(JSON.stringify(data, null, 2));
      message.success("자격 검증 완료");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const createMut = useMutation({
    mutationFn: () =>
      adminApi.createAiCandidateRecommendationQueue({
        reason,
        idempotency_key: `fe-queue-${Date.now()}`,
        source_type: sourceType,
        candidate_assessment_id:
          sourceType === "CANDIDATE_ASSESSMENT" ? assessmentId ?? undefined : undefined,
        candidate_consensus_id:
          sourceType === "CANDIDATE_CONSENSUS" ? consensusId ?? undefined : undefined,
        priority,
      }),
    onSuccess: (data) => {
      message.success("DRAFT 큐 생성 (미등록)");
      const id = asRecord(asRecord(data)?.queue)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const queueMut = useMutation({
    mutationFn: () =>
      adminApi.enqueueAiCandidateRecommendationQueue(selectedId!, { reason }),
    onSuccess: () => {
      message.success("QUEUED");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const assignMut = useMutation({
    mutationFn: () =>
      adminApi.assignAiCandidateRecommendationQueue(selectedId!, {
        reason,
        assignee_id: assigneeId,
      }),
    onSuccess: () => {
      message.success("ASSIGNED");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const startReviewMut = useMutation({
    mutationFn: () =>
      adminApi.startReviewAiCandidateRecommendationQueue(selectedId!, {
        reason,
        reviewer_id: reviewerId,
      }),
    onSuccess: (data) => {
      const reviewId = asRecord(asRecord(data)?.review)?.id;
      if (typeof reviewId === "number") setActiveReviewId(reviewId);
      message.success("UNDER_REVIEW");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const submitReviewMut = useMutation({
    mutationFn: () => {
      const reviewId = latestDraftReview;
      if (reviewId == null) {
        return Promise.reject(new Error("DRAFT review 없음"));
      }
      return adminApi.submitAiCandidateRecommendationQueueReview(reviewId, {
        reason,
        summary: "admin UI submit",
        recommendation_scope: "CONSIDERATION_ONLY",
        ...DEFAULT_RUBRIC,
      });
    },
    onSuccess: () => {
      message.success("Review 제출 (overall 서버 계산)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const decideMut = useMutation({
    mutationFn: () =>
      adminApi.decideAiCandidateRecommendationQueue(selectedId!, {
        decision,
        decision_reason: reason,
        manager_override: managerOverride,
        override_reason: managerOverride ? overrideReason || reason : undefined,
      }),
    onSuccess: () => {
      message.success("결정 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const holdMut = useMutation({
    mutationFn: () =>
      adminApi.holdAiCandidateRecommendationQueue(selectedId!, { reason }),
    onSuccess: () => {
      message.success("ON_HOLD");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const resumeMut = useMutation({
    mutationFn: () =>
      adminApi.resumeAiCandidateRecommendationQueue(selectedId!, { reason }),
    onSuccess: () => {
      message.success("RESUMED");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const revalidateMut = useMutation({
    mutationFn: () =>
      adminApi.revalidateAiCandidateRecommendationQueue(selectedId!, {}),
    onSuccess: (data) => {
      setValidateResult(JSON.stringify(data, null, 2));
      message.success("Revalidated");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const runCompare = async () => {
    if (selectedId == null || compareLeft == null) {
      message.error("compare id 필요");
      return;
    }
    try {
      const data = await adminApi.compareAiCandidateRecommendationQueues({
        left_id: selectedId,
        right_id: compareLeft,
      });
      setCompareResult(JSON.stringify(data, null, 2));
    } catch (e) {
      message.error(toApiError(e).message);
    }
  };

  return (
    <AdminPageShell title="후보 추천 검토 큐">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Alert type="warning" showIcon title={REFERENCE_DISCLAIMER} />

        <Space wrap>
          <Tag>DRAFT: {cell(statusCounts.DRAFT)}</Tag>
          <Tag>QUEUED: {cell(statusCounts.QUEUED)}</Tag>
          <Tag>UNDER_REVIEW: {cell(statusCounts.UNDER_REVIEW)}</Tag>
          <Tag color="green">
            {CONSIDERATION_LABEL}: {cell(statusCounts.APPROVED_FOR_CONSIDERATION)}
          </Tag>
          <Tag>Expiring ≤6h: {cell(dash.expiring_within_6h)}</Tag>
        </Space>

        <Space wrap>
          <Space.Compact>
            <Input style={{ width: 80 }} value="reason" disabled />
            <Input
              placeholder="reason (필수)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              style={{ width: 280 }}
            />
          </Space.Compact>
          <Select
            value={sourceType}
            onChange={setSourceType}
            options={[
              { value: "CANDIDATE_ASSESSMENT", label: "Assessment" },
              { value: "CANDIDATE_CONSENSUS", label: "Consensus" },
            ]}
            style={{ width: 180 }}
          />
          {sourceType === "CANDIDATE_ASSESSMENT" ? (
            <Space.Compact>
              <Input style={{ width: 120 }} value="assessment_id" disabled />
              <InputNumber
                value={assessmentId ?? undefined}
                onChange={(v) => setAssessmentId(v == null ? null : Number(v))}
              />
            </Space.Compact>
          ) : (
            <Space.Compact>
              <Input style={{ width: 120 }} value="consensus_id" disabled />
              <InputNumber
                value={consensusId ?? undefined}
                onChange={(v) => setConsensusId(v == null ? null : Number(v))}
              />
            </Space.Compact>
          )}
          <Select
            value={priority}
            onChange={setPriority}
            options={["LOW", "NORMAL", "HIGH", "URGENT"].map((v) => ({
              value: v,
              label: v,
            }))}
            style={{ width: 120 }}
          />
          <Button onClick={() => validateMut.mutate()} loading={validateMut.isPending}>
            Validate
          </Button>
          <Button
            type="primary"
            onClick={() => requireReason() && createMut.mutate()}
            loading={createMut.isPending}
          >
            Create (DRAFT)
          </Button>
        </Space>

        {validateResult ? (
          <pre style={{ whiteSpace: "pre-wrap", maxHeight: 160, overflow: "auto" }}>
            {validateResult}
          </pre>
        ) : null}

        <Space wrap>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && queueMut.mutate()}
            loading={queueMut.isPending}
          >
            Queue
          </Button>
          <Space.Compact>
            <Input style={{ width: 100 }} value="assignee" disabled />
            <Input
              value={assigneeId}
              onChange={(e) => setAssigneeId(e.target.value)}
              style={{ width: 140 }}
            />
          </Space.Compact>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && assignMut.mutate()}
            loading={assignMut.isPending}
          >
            Assign
          </Button>
          <Space.Compact>
            <Input style={{ width: 100 }} value="reviewer" disabled />
            <Input
              value={reviewerId}
              onChange={(e) => setReviewerId(e.target.value)}
              style={{ width: 140 }}
            />
          </Space.Compact>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && startReviewMut.mutate()}
            loading={startReviewMut.isPending}
          >
            Start Review
          </Button>
          <Button
            disabled={selectedId == null || latestDraftReview == null}
            onClick={() => requireReason() && submitReviewMut.mutate()}
            loading={submitReviewMut.isPending}
          >
            Submit Review
          </Button>
          <Select
            value={decision}
            onChange={setDecision}
            options={DECISION_OPTIONS}
            style={{ width: 260 }}
          />
          <Checkbox
            checked={managerOverride}
            onChange={(e) => setManagerOverride(e.target.checked)}
          >
            manager override
          </Checkbox>
          {managerOverride ? (
            <Input
              placeholder="override reason"
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
              style={{ width: 200 }}
            />
          ) : null}
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && decideMut.mutate()}
            loading={decideMut.isPending}
          >
            Decide
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && holdMut.mutate()}
            loading={holdMut.isPending}
          >
            Hold
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && resumeMut.mutate()}
            loading={resumeMut.isPending}
          >
            Resume
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => revalidateMut.mutate()}
            loading={revalidateMut.isPending}
          >
            Revalidate
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
            { title: "Source", dataIndex: "source_type", width: 160 },
            { title: "Market", dataIndex: "market_type", width: 90 },
            { title: "Symbol", dataIndex: "symbol", width: 100 },
            { title: "Status", dataIndex: "queue_status", width: 200 },
            { title: "Priority", dataIndex: "priority", width: 90 },
            { title: "Assigned", dataIndex: "assigned_to", width: 120 },
            { title: "Analytical", dataIndex: "analytical_score", width: 90 },
            { title: "Risk", dataIndex: "risk_score", width: 70 },
          ]}
        />

        {detail ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Title level={5}>상세 #{cell(detail.id)}</Typography.Title>
            <Typography.Paragraph type="secondary">
              {REFERENCE_DISCLAIMER}
            </Typography.Paragraph>
            <Space wrap>
              <Tag>Status: {cell(detail.queue_status)}</Tag>
              <Tag>Source: {cell(detail.source_type)}</Tag>
              <Tag>{CONSIDERATION_LABEL}</Tag>
              <Tag>Analytical: {cell(detail.analytical_score)}</Tag>
              <Tag>Risk: {cell(detail.risk_score)}</Tag>
              <Tag>Confidence: {cell(detail.confidence)}</Tag>
              <Tag>Expires: {cell(detail.expires_at)}</Tag>
              <Typography.Link href={adminRoutes.aiCandidatePromotions}>
                Candidate Promotion 요청
              </Typography.Link>
            </Space>

            <Typography.Title level={5}>Reviews</Typography.Title>
            <Table
              rowKey={(r) => String(asRecord(r)?.id ?? "")}
              size="small"
              pagination={false}
              dataSource={reviewItems}
              columns={[
                { title: "ID", dataIndex: "id", width: 60 },
                { title: "Ver", dataIndex: "review_version", width: 50 },
                { title: "Status", dataIndex: "review_status", width: 100 },
                { title: "Overall", dataIndex: "overall_score", width: 80 },
                { title: "Safety", dataIndex: "safety_score", width: 70 },
                { title: "Scope", dataIndex: "recommendation_scope", width: 140 },
              ]}
            />

            <Typography.Title level={5}>Findings</Typography.Title>
            <Table
              rowKey={(r) => String(asRecord(r)?.id ?? "")}
              size="small"
              pagination={false}
              dataSource={findingItems}
              columns={[
                { title: "Type", dataIndex: "finding_type", width: 160 },
                { title: "Severity", dataIndex: "severity", width: 90 },
                { title: "Field", dataIndex: "field_path", width: 120 },
                { title: "Resolution", dataIndex: "resolution_status", width: 110 },
                { title: "Description", dataIndex: "description_sanitized", ellipsis: true },
              ]}
            />

            <Typography.Title level={5}>Decisions</Typography.Title>
            <Table
              rowKey={(r) => String(asRecord(r)?.id ?? "")}
              size="small"
              pagination={false}
              dataSource={decisionItems}
              columns={[
                { title: "Decision", dataIndex: "decision", width: 220 },
                { title: "By", dataIndex: "decided_by", width: 120 },
                { title: "Override", dataIndex: "manager_override", width: 80 },
                { title: "Critical", dataIndex: "critical_findings_count", width: 80 },
                { title: "Reason", dataIndex: "decision_reason", ellipsis: true },
              ]}
            />

            <Typography.Title level={5}>History</Typography.Title>
            <Table
              rowKey={(r) => String(asRecord(r)?.id ?? "")}
              size="small"
              pagination={{ pageSize: 5 }}
              dataSource={historyItems}
              columns={[
                { title: "Action", dataIndex: "action", width: 180 },
                { title: "Prev", dataIndex: "previous_status", width: 140 },
                { title: "New", dataIndex: "new_status", width: 140 },
                { title: "By", dataIndex: "requested_by", width: 120 },
                { title: "At", dataIndex: "created_at", width: 180 },
              ]}
            />

            <Space>
              <Space.Compact>
                <Input style={{ width: 100 }} value="compare id" disabled />
                <InputNumber
                  placeholder="other queue id"
                  value={compareLeft ?? undefined}
                  onChange={(v) => setCompareLeft(v == null ? null : Number(v))}
                />
              </Space.Compact>
              <Button onClick={runCompare}>Compare</Button>
            </Space>
            {compareResult ? (
              <pre style={{ whiteSpace: "pre-wrap" }}>{compareResult}</pre>
            ) : null}
          </Space>
        ) : null}
      </Space>
    </AdminPageShell>
  );
}
