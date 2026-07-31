"use client";

/**
 * STEP 11-10 — Multi-AI Candidate Consensus 초안.
 * 참고용만. 매수/매도/주문/후보등록 버튼 없음. create ≠ calculate ≠ synthesize.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Checkbox,
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
import { useMemo, useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const REFERENCE_DISCLAIMER =
  "Multi-AI Consensus는 여러 AI 후보 평가를 비교한 참고용 품질 합의 초안이며, " +
  "실제 후보 등록·매수·매도·주문 지시가 아닙니다.";
const REVIEW_QUALITY_LABEL = "AI Consensus 품질 승인";

/** 쉼표·공백 구분 assessment ID 파싱 */
function parseAssessmentIds(raw: string): number[] {
  return raw
    .split(/[,\s]+/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => Number(part))
    .filter((id) => Number.isFinite(id) && id > 0);
}

export default function AdminAiCandidateConsensusesPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [compareLeft, setCompareLeft] = useState<number | null>(null);
  const [marketType, setMarketType] = useState("STOCK");
  const [exchange, setExchange] = useState("KRX");
  const [symbol, setSymbol] = useState("005930");
  const [instrumentId, setInstrumentId] = useState<number | null>(null);
  const [assessmentIdsRaw, setAssessmentIdsRaw] = useState("1,2");
  const [calculationMode, setCalculationMode] = useState("DETERMINISTIC_ONLY");
  const [synthesisMode, setSynthesisMode] = useState("MOCK");
  const [requireReviewedMembers, setRequireReviewedMembers] = useState(false);
  const [minimumProviderFamilies, setMinimumProviderFamilies] = useState(1);
  const [dryResult, setDryResult] = useState("");
  const [compareResult, setCompareResult] = useState("");

  const assessmentIds = useMemo(
    () => parseAssessmentIds(assessmentIdsRaw),
    [assessmentIdsRaw],
  );

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiCandidateConsensuses(),
    queryFn: () => adminApi.listAiCandidateConsensuses(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-candidate-consensus", selectedId],
    queryFn: () => adminApi.getAiCandidateConsensus(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(asRecord(detailQuery.data)?.consensus);

  const membersQuery = useQuery({
    queryKey: ["admin", "ai-candidate-consensus-members", selectedId],
    queryFn: () => adminApi.getAiCandidateConsensusMembers(selectedId!),
    enabled: selectedId != null,
  });
  const memberItems = extractRows(asRecord(membersQuery.data)?.items);

  const conflictsQuery = useQuery({
    queryKey: ["admin", "ai-candidate-consensus-conflicts", selectedId],
    queryFn: () => adminApi.getAiCandidateConsensusConflicts(selectedId!),
    enabled: selectedId != null,
  });
  const conflictItems = extractRows(asRecord(conflictsQuery.data)?.items);

  const historyQuery = useQuery({
    queryKey: ["admin", "ai-candidate-consensus-history", selectedId],
    queryFn: () => adminApi.getAiCandidateConsensusHistory(selectedId!),
    enabled: selectedId != null,
  });
  const historyItems = extractRows(asRecord(historyQuery.data)?.items);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-candidate-consensus-dashboard"],
    queryFn: adminApi.getAiCandidateConsensusDashboard,
  });
  const dash = asRecord(dashQuery.data);

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiCandidateConsensuses(),
    });
    queryClient.invalidateQueries({
      queryKey: ["admin", "ai-candidate-consensus-dashboard"],
    });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-consensus", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-consensus-members", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-consensus-conflicts", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-consensus-history", selectedId],
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
    mutationFn: () => {
      if (assessmentIds.length < 2) {
        return Promise.reject(new Error("assessment_ids 2개 이상 필요"));
      }
      return adminApi.createAiCandidateConsensus({
        reason,
        idempotency_key: `fe-cons-${Date.now()}`,
        market_type: marketType,
        exchange_code: exchange,
        symbol,
        instrument_id: instrumentId ?? undefined,
        assessment_ids: assessmentIds,
        calculation_mode: calculationMode,
        synthesis_execution_mode: synthesisMode,
        synthesis_provider_code: synthesisMode === "MOCK" ? "mock" : undefined,
        require_reviewed_members: requireReviewedMembers,
        minimum_provider_families: minimumProviderFamilies,
      });
    },
    onSuccess: (data) => {
      message.success("합의 초안 생성 (미계산)");
      const id = asRecord(asRecord(data)?.consensus)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const dryMut = useMutation({
    mutationFn: () =>
      adminApi.dryRunAiCandidateConsensus(selectedId!, { reason }),
    onSuccess: (data) => {
      setDryResult(JSON.stringify(data, null, 2));
      message.success("Dry-run 완료 (외부 호출 0)");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const calculateMut = useMutation({
    mutationFn: () =>
      adminApi.calculateAiCandidateConsensus(selectedId!, { reason }),
    onSuccess: () => {
      message.success("Deterministic 계산 완료 (외부 호출 0)");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const synthesizeMut = useMutation({
    mutationFn: () =>
      adminApi.synthesizeAiCandidateConsensus(selectedId!, {
        reason,
        confirm: synthesisMode === "EXTERNAL",
      }),
    onSuccess: () => {
      message.success("Meta-Synthesis 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const cancelMut = useMutation({
    mutationFn: () =>
      adminApi.cancelAiCandidateConsensus(selectedId!, { reason }),
    onSuccess: () => {
      message.success("취소됨");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const recalculateMut = useMutation({
    mutationFn: () =>
      adminApi.recalculateAiCandidateConsensus(selectedId!, {
        reason,
        idempotency_key: `fe-recalc-${selectedId}-${Date.now()}`,
      }),
    onSuccess: (data) => {
      message.success("재계산 초안 생성");
      const id = asRecord(asRecord(data)?.consensus)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const reviewMut = useMutation({
    mutationFn: () =>
      adminApi.requestReviewAiCandidateConsensus(selectedId!, { reason }),
    onSuccess: () => {
      message.success(`${REVIEW_QUALITY_LABEL} 요청됨`);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const confirmSynthesize = () => {
    if (!requireReason() || selectedId == null) return;
    Modal.confirm({
      title: "Meta-Synthesis 실행",
      content: (
        <div>
          <p>{REFERENCE_DISCLAIMER}</p>
          <p>
            Mode={synthesisMode} / 참고용 합의 초안 / 매매·주문·후보등록과 무관
          </p>
        </div>
      ),
      onOk: () => synthesizeMut.mutateAsync(),
    });
  };

  const runCompare = async () => {
    if (compareLeft == null || selectedId == null) {
      message.error("비교할 두 ID 필요");
      return;
    }
    try {
      const data = await adminApi.compareAiCandidateConsensuses({
        left_id: compareLeft,
        right_id: selectedId,
      });
      setCompareResult(JSON.stringify(data, null, 2));
    } catch (e) {
      message.error(toApiError(e).message);
    }
  };

  const onMarketTypeChange = (value: string) => {
    setMarketType(value);
    setExchange(value === "CRYPTO" ? "UPBIT" : "KRX");
  };

  const synthesisEnabled =
    calculationMode === "DETERMINISTIC_PLUS_SYNTHESIS" &&
    detail?.consensus_status != null &&
    !["DRAFT", "CANCELLED", "SUPERSEDED"].includes(
      String(detail.consensus_status),
    );

  return (
    <AdminPageShell
      title="Multi-AI 합의 초안"
      description="다중 AI 후보 평가 합의 초안 (참고용). create/calculate/synthesize 분리. Deterministic 기본."
    >
      <Alert
        type="warning"
        showIcon
        title={REFERENCE_DISCLAIMER}
        style={{ marginBottom: 16 }}
      />
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text>
            Today: {cell(dash?.consensus_today)} / Stock:{" "}
            {cell(dash?.stock_consensus)} / Crypto: {cell(dash?.crypto_consensus)}
          </Typography.Text>
          <Tag>Calculated {cell(dash?.calculated)}</Tag>
          <Tag>Review {cell(dash?.review_pending)}</Tag>
          <Tag color="orange">Split/Weak {cell(dash?.split_or_weak)}</Tag>
          <Typography.Link href={adminRoutes.aiCandidateAssessments}>
            후보 평가 초안 →
          </Typography.Link>
        </Space>

        <Space wrap>
          <Input
            placeholder="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ width: 200 }}
          />
          <Select
            value={marketType}
            onChange={onMarketTypeChange}
            options={[
              { value: "STOCK", label: "STOCK" },
              { value: "CRYPTO", label: "CRYPTO" },
            ]}
            style={{ width: 110 }}
          />
          <Select
            value={exchange}
            onChange={setExchange}
            options={[
              { value: "KRX", label: "KRX" },
              { value: "UPBIT", label: "UPBIT" },
            ]}
            style={{ width: 100 }}
          />
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="symbol"
            style={{ width: 120 }}
          />
          <Space.Compact>
            <Input style={{ width: 100 }} value="instrument_id" disabled />
            <InputNumber
              min={1}
              value={instrumentId ?? undefined}
              onChange={(v) =>
                setInstrumentId(v == null ? null : Number(v))
              }
              placeholder="optional"
            />
          </Space.Compact>
          <Input
            value={assessmentIdsRaw}
            onChange={(e) => setAssessmentIdsRaw(e.target.value)}
            placeholder="assessment_ids (comma)"
            style={{ width: 180 }}
          />
          <Select
            value={calculationMode}
            onChange={setCalculationMode}
            options={[
              { value: "DETERMINISTIC_ONLY", label: "DETERMINISTIC_ONLY" },
              {
                value: "DETERMINISTIC_PLUS_SYNTHESIS",
                label: "DETERMINISTIC_PLUS_SYNTHESIS",
              },
            ]}
            style={{ width: 240 }}
          />
          <Select
            value={synthesisMode}
            onChange={setSynthesisMode}
            options={[
              { value: "MOCK", label: "MOCK" },
              { value: "DRY_RUN", label: "DRY_RUN" },
              { value: "EXTERNAL", label: "EXTERNAL" },
            ]}
            style={{ width: 110 }}
          />
          <Button
            type="primary"
            onClick={() => requireReason() && createMut.mutate()}
            loading={createMut.isPending}
          >
            합의 초안 생성
          </Button>
        </Space>

        <Space wrap>
          <Checkbox
            checked={requireReviewedMembers}
            onChange={(e) => setRequireReviewedMembers(e.target.checked)}
          >
            Reviewed members only
          </Checkbox>
          <Space.Compact>
            <Input style={{ width: 160 }} value="min provider families" disabled />
            <InputNumber
              min={1}
              max={5}
              value={minimumProviderFamilies}
              onChange={(v) =>
                setMinimumProviderFamilies(v == null ? 1 : Number(v))
              }
            />
          </Space.Compact>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && dryMut.mutate()}
            loading={dryMut.isPending}
          >
            Dry-run
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && calculateMut.mutate()}
            loading={calculateMut.isPending}
          >
            Calculate (deterministic)
          </Button>
          <Button
            disabled={selectedId == null || !synthesisEnabled}
            onClick={confirmSynthesize}
            loading={synthesizeMut.isPending}
          >
            Synthesize
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && cancelMut.mutate()}
            loading={cancelMut.isPending}
          >
            Cancel
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && recalculateMut.mutate()}
            loading={recalculateMut.isPending}
          >
            Recalculate
          </Button>
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && reviewMut.mutate()}
            loading={reviewMut.isPending}
          >
            {REVIEW_QUALITY_LABEL}
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
            { title: "Market", dataIndex: "market_type", width: 90 },
            { title: "Exchange", dataIndex: "exchange_code", width: 90 },
            { title: "Symbol", dataIndex: "symbol", width: 100 },
            { title: "Status", dataIndex: "consensus_status", width: 160 },
            { title: "Agreement", dataIndex: "agreement_level", width: 150 },
            { title: "Analytical", dataIndex: "analytical_score", width: 90 },
            { title: "Risk", dataIndex: "risk_score", width: 70 },
            { title: "Confidence", dataIndex: "confidence", width: 100 },
            { title: "Members", dataIndex: "included_count", width: 80 },
            { title: "Mode", dataIndex: "calculation_mode", width: 200 },
          ]}
        />

        {detail ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Title level={5}>상세 #{cell(detail.id)}</Typography.Title>
            <Typography.Paragraph type="secondary">
              {REFERENCE_DISCLAIMER}
            </Typography.Paragraph>
            <Space wrap>
              <Tag>Status: {cell(detail.consensus_status)}</Tag>
              <Tag>Agreement: {cell(detail.agreement_level)}</Tag>
              <Tag>Disagreement: {cell(detail.disagreement_level)}</Tag>
              <Tag>Analytical: {cell(detail.analytical_score)}</Tag>
              <Tag>Risk: {cell(detail.risk_score)}</Tag>
              <Tag>Confidence: {cell(detail.confidence)}</Tag>
              <Tag>Evidence: {cell(detail.evidence_consistency)}</Tag>
              <Tag>Diversity: {cell(detail.provider_diversity)}</Tag>
              <Tag
                color={
                  detail.agreement_level === "SPLIT" ||
                  detail.agreement_level === "WEAK_AGREEMENT"
                    ? "orange"
                    : "default"
                }
              >
                Split/Weak:{" "}
                {detail.agreement_level === "SPLIT" ||
                detail.agreement_level === "WEAK_AGREEMENT"
                  ? "yes"
                  : "no"}
              </Tag>
            </Space>
            {String(detail.consensus_status ?? "").startsWith("REVIEW") ? (
              <Space orientation="vertical" size={4}>
                <Typography.Text strong>{REVIEW_QUALITY_LABEL}</Typography.Text>
                <Typography.Link href={adminRoutes.aiReviews}>
                  Human Review 페이지 →
                </Typography.Link>
              </Space>
            ) : null}
            <Typography.Link href={adminRoutes.aiCandidateRecommendationQueues}>
              검토 큐 등록 →
            </Typography.Link>
            <Typography.Title level={5}>Members</Typography.Title>
            <Table
              rowKey={(r) => String(asRecord(r)?.id ?? "")}
              size="small"
              pagination={false}
              dataSource={memberItems}
              columns={[
                { title: "Assessment", dataIndex: "assessment_id", width: 90 },
                { title: "Provider", dataIndex: "provider_code", width: 100 },
                { title: "Model", dataIndex: "model", width: 120 },
                { title: "Included", dataIndex: "included", width: 80 },
                { title: "Independence", dataIndex: "independence_status", width: 140 },
                { title: "Weight", dataIndex: "final_weight", width: 80 },
                { title: "Analytical", dataIndex: "analytical_score", width: 90 },
                { title: "Risk", dataIndex: "risk_score", width: 70 },
                { title: "Confidence", dataIndex: "confidence", width: 90 },
                { title: "Review", dataIndex: "review_decision", width: 120 },
              ]}
            />
            <Typography.Title level={5}>Conflicts</Typography.Title>
            <Table
              rowKey={(r) => String(asRecord(r)?.id ?? "")}
              size="small"
              pagination={false}
              dataSource={conflictItems}
              columns={[
                { title: "Type", dataIndex: "conflict_type", width: 120 },
                { title: "Severity", dataIndex: "severity", width: 90 },
                { title: "Field", dataIndex: "field_path", width: 120 },
                { title: "Assessments", dataIndex: "assessment_ids", width: 120 },
                { title: "Status", dataIndex: "resolution_status", width: 110 },
                { title: "Description", dataIndex: "description", ellipsis: true },
              ]}
            />
            <Typography.Title level={5}>History</Typography.Title>
            <Table
              rowKey={(r) => String(asRecord(r)?.id ?? "")}
              size="small"
              pagination={{ pageSize: 5 }}
              dataSource={historyItems}
              columns={[
                { title: "Action", dataIndex: "action", width: 220 },
                { title: "Prev", dataIndex: "previous_status", width: 120 },
                { title: "New", dataIndex: "new_status", width: 120 },
                { title: "By", dataIndex: "requested_by", width: 120 },
                { title: "At", dataIndex: "created_at", width: 180 },
              ]}
            />
            <Typography.Title level={5}>Safe Result</Typography.Title>
            <pre style={{ whiteSpace: "pre-wrap" }}>
              {JSON.stringify(detail.safe_result ?? {}, null, 2)}
            </pre>
            <Space>
              <Space.Compact>
                <Input style={{ width: 100 }} value="left id" disabled />
                <InputNumber
                  placeholder="compare left id"
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

        {dryResult ? (
          <pre style={{ whiteSpace: "pre-wrap", maxHeight: 240, overflow: "auto" }}>
            {dryResult}
          </pre>
        ) : null}
      </Space>
    </AdminPageShell>
  );
}
