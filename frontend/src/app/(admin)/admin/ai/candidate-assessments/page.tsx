"use client";

/**
 * STEP 11-9 — AI 후보 평가 초안.
 * 참고용만. 매수/매도/주문/후보등록 버튼 없음. create ≠ execute.
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
import { useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const DISCLAIMER =
  "AI 후보 평가는 참고용 초안이며, 실제 매매 후보·매수·매도 신호 또는 주문 지시가 아닙니다.";
const REVIEW_QUALITY_LABEL = "AI 후보 평가 품질 승인";

export default function AdminAiCandidateAssessmentsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [compareLeft, setCompareLeft] = useState<number | null>(null);
  const [marketType, setMarketType] = useState("STOCK");
  const [exchange, setExchange] = useState("KRX");
  const [symbol, setSymbol] = useState("005930");
  const [instrumentId, setInstrumentId] = useState<number | null>(null);
  const [mode, setMode] = useState("MOCK");
  const [includeNews, setIncludeNews] = useState(true);
  const [includeDisclosure, setIncludeDisclosure] = useState(true);
  const [includeChart, setIncludeChart] = useState(true);
  const [includeMarket, setIncludeMarket] = useState(true);
  const [requireReviewedEvidence, setRequireReviewedEvidence] = useState(false);
  const [dryResult, setDryResult] = useState("");
  const [compareResult, setCompareResult] = useState("");

  const listQuery = useQuery({
    queryKey: queryKeys.admin.aiCandidateAssessments(),
    queryFn: () => adminApi.listAiCandidateAssessments(),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: ["admin", "ai-candidate-assessment", selectedId],
    queryFn: () => adminApi.getAiCandidateAssessment(selectedId!),
    enabled: selectedId != null,
  });
  const detail = asRecord(asRecord(detailQuery.data)?.assessment);

  const evidenceQuery = useQuery({
    queryKey: ["admin", "ai-candidate-assessment-evidence", selectedId],
    queryFn: () => adminApi.getAiCandidateAssessmentEvidence(selectedId!),
    enabled: selectedId != null,
  });
  const evidenceItems = extractRows(asRecord(evidenceQuery.data)?.items);

  const historyQuery = useQuery({
    queryKey: ["admin", "ai-candidate-assessment-history", selectedId],
    queryFn: () => adminApi.getAiCandidateAssessmentHistory(selectedId!),
    enabled: selectedId != null,
  });
  const historyItems = extractRows(asRecord(historyQuery.data)?.items);

  const dashQuery = useQuery({
    queryKey: ["admin", "ai-candidate-assessment-dashboard"],
    queryFn: adminApi.getAiCandidateAssessmentDashboard,
  });
  const dash = asRecord(dashQuery.data);

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: queryKeys.admin.aiCandidateAssessments(),
    });
    queryClient.invalidateQueries({
      queryKey: ["admin", "ai-candidate-assessment-dashboard"],
    });
    if (selectedId != null) {
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-assessment", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-assessment-evidence", selectedId],
      });
      queryClient.invalidateQueries({
        queryKey: ["admin", "ai-candidate-assessment-history", selectedId],
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
      adminApi.createAiCandidateAssessment({
        reason,
        idempotency_key: `fe-cand-${Date.now()}`,
        market_type: marketType,
        exchange_code: exchange,
        symbol,
        instrument_id: instrumentId ?? undefined,
        execution_mode: mode,
        provider_code: mode === "MOCK" ? "mock" : undefined,
        include_news: includeNews,
        include_disclosure: includeDisclosure,
        include_chart: includeChart,
        include_market: includeMarket,
        require_reviewed_evidence: requireReviewedEvidence,
      }),
    onSuccess: (data) => {
      message.success("평가 초안 생성 (미실행)");
      const id = asRecord(asRecord(data)?.assessment)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const dryMut = useMutation({
    mutationFn: () =>
      adminApi.dryRunAiCandidateAssessment(selectedId!, { reason }),
    onSuccess: (data) => {
      setDryResult(JSON.stringify(data, null, 2));
      message.success("Dry-run 완료 (외부 호출 0)");
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const execMut = useMutation({
    mutationFn: () =>
      adminApi.executeAiCandidateAssessment(selectedId!, {
        reason,
        confirm: mode === "EXTERNAL",
      }),
    onSuccess: () => {
      message.success("실행 완료");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const cancelMut = useMutation({
    mutationFn: () =>
      adminApi.cancelAiCandidateAssessment(selectedId!, { reason }),
    onSuccess: () => {
      message.success("취소됨");
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const reassessMut = useMutation({
    mutationFn: () =>
      adminApi.reassessAiCandidateAssessment(selectedId!, {
        reason,
        idempotency_key: `fe-re-${selectedId}-${Date.now()}`,
      }),
    onSuccess: (data) => {
      message.success("재평가 초안 생성");
      const id = asRecord(asRecord(data)?.assessment)?.id;
      if (typeof id === "number") setSelectedId(id);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const reviewMut = useMutation({
    mutationFn: () =>
      adminApi.requestReviewAiCandidateAssessment(selectedId!, { reason }),
    onSuccess: () => {
      message.success(`${REVIEW_QUALITY_LABEL} 요청됨`);
      invalidate();
    },
    onError: (e) => message.error(toApiError(e).message),
  });

  const confirmExecute = () => {
    if (!requireReason() || selectedId == null) return;
    Modal.confirm({
      title: "후보 평가 초안 실행",
      content: (
        <div>
          <p>{DISCLAIMER}</p>
          <p>
            Mode={mode} / 참고용 초안 / 매매·주문·후보등록과 무관
          </p>
        </div>
      ),
      onOk: () => execMut.mutateAsync(),
    });
  };

  const runCompare = async () => {
    if (compareLeft == null || selectedId == null) {
      message.error("비교할 두 ID 필요");
      return;
    }
    try {
      const data = await adminApi.compareAiCandidateAssessments({
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

  return (
    <AdminPageShell
      title="후보 평가 초안"
      description="다중 근거 기반 AI 후보 평가 초안 (참고용). 수집과 실행 분리. Mock 기본."
    >
      <Alert type="warning" showIcon title={DISCLAIMER} style={{ marginBottom: 16 }} />
      <Space orientation="vertical" size={16} style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Text>
            Today: {cell(dash?.assessments_today)} / Stock:{" "}
            {cell(dash?.stock_assessments)} / Crypto: {cell(dash?.crypto_assessments)}
          </Typography.Text>
          <Tag>Running {cell(dash?.running)}</Tag>
          <Tag>Succeeded {cell(dash?.succeeded)}</Tag>
          <Tag>Review {cell(dash?.review_pending)}</Tag>
          <Tag color="orange">Conflict {cell(dash?.major_conflict)}</Tag>
          <Typography.Link href={adminRoutes.aiCandidateConsensuses}>
            Multi-AI 합의 초안 →
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
          <Select
            value={mode}
            onChange={setMode}
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
            평가 초안 생성
          </Button>
        </Space>

        <Space wrap>
          <Checkbox checked={includeNews} onChange={(e) => setIncludeNews(e.target.checked)}>
            News
          </Checkbox>
          <Checkbox
            checked={includeDisclosure}
            onChange={(e) => setIncludeDisclosure(e.target.checked)}
          >
            Disclosure
          </Checkbox>
          <Checkbox checked={includeChart} onChange={(e) => setIncludeChart(e.target.checked)}>
            Chart
          </Checkbox>
          <Checkbox checked={includeMarket} onChange={(e) => setIncludeMarket(e.target.checked)}>
            Market
          </Checkbox>
          <Checkbox
            checked={requireReviewedEvidence}
            onChange={(e) => setRequireReviewedEvidence(e.target.checked)}
          >
            Reviewed evidence only
          </Checkbox>
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
          <Button
            disabled={selectedId == null}
            onClick={() => requireReason() && reassessMut.mutate()}
            loading={reassessMut.isPending}
          >
            Reassess
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
            { title: "Status", dataIndex: "assessment_status", width: 160 },
            { title: "Analytical", dataIndex: "analytical_score", width: 90 },
            { title: "Risk", dataIndex: "risk_score", width: 70 },
            { title: "Confidence", dataIndex: "confidence", width: 100 },
            { title: "Conflict", dataIndex: "conflict_status", width: 130 },
            { title: "Mode", dataIndex: "execution_mode", width: 90 },
          ]}
        />

        {detail ? (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Title level={5}>상세 #{cell(detail.id)}</Typography.Title>
            <Typography.Paragraph type="secondary">{DISCLAIMER}</Typography.Paragraph>
            <Space wrap>
              <Tag>Status: {cell(detail.assessment_status)}</Tag>
              <Tag>Analytical: {cell(detail.analytical_score)}</Tag>
              <Tag>Risk: {cell(detail.risk_score)}</Tag>
              <Tag>Overall: {cell(detail.overall_score)}</Tag>
              <Tag>Confidence: {cell(detail.confidence)}</Tag>
              <Tag>Evidence Q: {cell(detail.evidence_quality)}</Tag>
              <Tag>Data Q: {cell(detail.data_quality)}</Tag>
              <Tag color={detail.conflict_status === "MAJOR_CONFLICT" ? "red" : "default"}>
                Conflict: {cell(detail.conflict_status)}
              </Tag>
              <Tag>Temporal: {cell(detail.temporal_alignment_status)}</Tag>
            </Space>
            {detail.review_decision ? (
              <Space orientation="vertical" size={4}>
                <Typography.Text strong>{REVIEW_QUALITY_LABEL} 상태</Typography.Text>
                <Tag>{cell(detail.review_decision)}</Tag>
                <Typography.Link href={adminRoutes.aiReviews}>
                  Human Review 페이지 →
                </Typography.Link>
              </Space>
            ) : null}
            <Typography.Link href={adminRoutes.aiCandidateRecommendationQueues}>
              검토 큐 등록 →
            </Typography.Link>
            <Typography.Title level={5}>근거 (Evidence)</Typography.Title>
            <Table
              rowKey={(r) => String(asRecord(r)?.id ?? "")}
              size="small"
              pagination={false}
              dataSource={evidenceItems}
              columns={[
                { title: "Type", dataIndex: "evidence_type", width: 100 },
                { title: "Source", dataIndex: "source_analysis_type", width: 120 },
                { title: "Direction", dataIndex: "direction", width: 90 },
                { title: "Quality", dataIndex: "quality_status", width: 100 },
                { title: "Included", dataIndex: "included", width: 80 },
                { title: "Summary", dataIndex: "summary", ellipsis: true },
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
