"use client";

/**
 * STEP 12-2-1/12-2-2 — Strategy Draft 저장/버전관리 + AI 생성(관리자).
 * 승인(APPROVED)된 Strategy Request 위에 Draft를 저장·버전관리하고,
 * AI가 검토 전 Draft 초안을 생성하도록 요청할 수 있는 화면이다. 생성된
 * Draft는 검토 전 초안일 뿐이며, 자동 승인·Backtest·Paper Trading·
 * Runtime 등록·실주문으로 연결되지 않는다(STEP12-3 이후).
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
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useState } from "react";

import { adminRoutes } from "@/config/routes";
import * as adminApi from "@/features/admin/api/adminApi";
import { AdminPageShell } from "@/features/admin/components/AdminPageShell";
import { asRecord, cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

const STATUS_COLOR: Record<string, string> = {
  DRAFT: "processing",
  REGENERATED: "default",
  SUPERSEDED: "warning",
  ARCHIVED: "error",
};

const STATUS_OPTIONS = [
  { value: "", label: "전체" },
  { value: "DRAFT", label: "DRAFT" },
  { value: "REGENERATED", label: "REGENERATED" },
  { value: "SUPERSEDED", label: "SUPERSEDED" },
  { value: "ARCHIVED", label: "ARCHIVED" },
];

export default function AdminStrategyDraftsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [strategyRequestFilter, setStrategyRequestFilter] = useState<
    number | null
  >(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  // 새 Draft(새 Version) 생성 폼
  const [newRequestId, setNewRequestId] = useState<number | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [newTimeframe, setNewTimeframe] = useState("1D");
  const [newMarketType, setNewMarketType] = useState("KR_STOCK");
  const [newSummary, setNewSummary] = useState("");

  // 편집 폼(선택된 Draft의 내용 편집 — DRAFT 상태에서만 사용)
  const [editTitle, setEditTitle] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editEntryRule, setEditEntryRule] = useState("");
  const [editExitRule, setEditExitRule] = useState("");
  const [editReason, setEditReason] = useState("");

  const [versionView, setVersionView] = useState<{
    strategyRequestId: number;
    version: number;
  } | null>(null);

  // STEP12-2-2 — AI Strategy Draft 생성
  const [genRequestId, setGenRequestId] = useState<number | null>(null);

  // STEP12-2-3 — 비교/Generation 상세/Timeline
  const [compareDraftId, setCompareDraftId] = useState<number | null>(null);
  const [genRunDrawerId, setGenRunDrawerId] = useState<number | null>(null);
  const [timelineRequestId, setTimelineRequestId] = useState<number | null>(null);

  // STEP12-3 — 최종 승인/반려/취소
  const [approveReason, setApproveReason] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [revokeReason, setRevokeReason] = useState("");

  // STEP12-4 — Strategy Snapshot(승인으로 생성된 불변 Definition)
  const [snapshotDrawerId, setSnapshotDrawerId] = useState<number | null>(null);
  const [diffDefinitionId, setDiffDefinitionId] = useState<number | null>(null);

  // STEP12-8 — 직전 실행한 Backtest Run의 Performance Analytics 조회 여부
  const [showPerformanceForRunId, setShowPerformanceForRunId] = useState<
    number | null
  >(null);

  // STEP12-9 — Walk-Forward Analysis(Rolling/Expanding, In-Sample/Out-of-Sample)
  const [walkForwardTrainDays, setWalkForwardTrainDays] = useState<
    number | null
  >(45);
  const [walkForwardTestDays, setWalkForwardTestDays] = useState<
    number | null
  >(45);
  const [walkForwardScheme, setWalkForwardScheme] = useState<
    "ROLLING" | "EXPANDING"
  >("ROLLING");
  const [walkForwardRunId, setWalkForwardRunId] = useState<number | null>(null);

  // STEP12-10 — Strategy Quality Gate(자동 품질 심사)
  const [qualityGateReportId, setQualityGateReportId] = useState<number | null>(
    null,
  );

  // STEP12-11 — Parameter Sensitivity Analysis
  const [sensitivityParameterNames, setSensitivityParameterNames] = useState<
    string[]
  >([]);
  const [sensitivityReportId, setSensitivityReportId] = useState<number | null>(
    null,
  );

  // STEP12-12 — Monte Carlo Simulation(기존 Backtest Trade 재사용)
  const [monteCarloBacktestRunId, setMonteCarloBacktestRunId] = useState<
    number | null
  >(null);
  const [monteCarloMethod, setMonteCarloMethod] = useState<
    "TRADE_ORDER_SHUFFLE" | "BOOTSTRAP_WITH_REPLACEMENT" | "BLOCK_BOOTSTRAP"
  >("TRADE_ORDER_SHUFFLE");
  const [monteCarloCount, setMonteCarloCount] = useState<number | null>(1000);
  const [monteCarloSeed, setMonteCarloSeed] = useState<number | null>(42);
  const [monteCarloConfidenceLevel, setMonteCarloConfidenceLevel] = useState<
    "0.90" | "0.95" | "0.99"
  >("0.95");
  const [monteCarloRuinThreshold, setMonteCarloRuinThreshold] = useState<
    number | null
  >(50);
  const [monteCarloBlockSize, setMonteCarloBlockSize] = useState<number | null>(
    5,
  );
  const [monteCarloReportId, setMonteCarloReportId] = useState<number | null>(
    null,
  );

  // STEP12-14 — Strategy Explainability & Decision Evidence Layer
  const [explainBacktestRunId, setExplainBacktestRunId] = useState<
    number | null
  >(null);
  const [explainQualityGateReportId, setExplainQualityGateReportId] =
    useState<number | null>(null);
  const [explainSensitivityReportId, setExplainSensitivityReportId] =
    useState<number | null>(null);
  const [explainMonteCarloReportId, setExplainMonteCarloReportId] = useState<
    number | null
  >(null);
  const [explainUseLatestWhenMissing, setExplainUseLatestWhenMissing] =
    useState(true);
  const [explainabilityReportId, setExplainabilityReportId] = useState<
    number | null
  >(null);

  // STEP12-15 — Decision Package & Human Decision
  const [decisionPackageId, setDecisionPackageId] = useState<number | null>(
    null,
  );
  const [decisionType, setDecisionType] = useState<
    "APPROVE_FOR_PROMOTION" | "REQUEST_CHANGES" | "REJECT"
  >("APPROVE_FOR_PROMOTION");
  const [reasonCode, setReasonCode] = useState("EVIDENCE_REVIEW_COMPLETED");
  const [reasonText, setReasonText] = useState("");
  const [checklistConfirmations, setChecklistConfirmations] = useState<
    Record<string, boolean>
  >({});
  const [warningsAcknowledged, setWarningsAcknowledged] = useState(false);

  // STEP12-16 — Promotion Commit
  const [commitReason, setCommitReason] = useState("");
  const [confirmationText, setConfirmationText] = useState("");
  const [acknowledgeSameActorWarning, setAcknowledgeSameActorWarning] =
    useState(false);
  const [promotionCommitModalOpen, setPromotionCommitModalOpen] =
    useState(false);

  // STEP12-17 — Activation Review & Activation Commit
  const [activationReviewPackageId, setActivationReviewPackageId] = useState<
    number | null
  >(null);
  const [activationTargetMarketType, setActivationTargetMarketType] =
    useState("STOCK");
  const [activationTargetBrokerCode, setActivationTargetBrokerCode] =
    useState("PAPER");
  const [activationTargetAccountKind, setActivationTargetAccountKind] =
    useState("PAPER");
  const [activationTargetAccountId, setActivationTargetAccountId] = useState<
    number | null
  >(null);
  const [activationExecutionMode, setActivationExecutionMode] =
    useState("PAPER");
  const [activationReviewNote, setActivationReviewNote] = useState("");
  const [activationDecisionType, setActivationDecisionType] = useState(
    "APPROVE_ACTIVATION",
  );
  const [activationReasonCode, setActivationReasonCode] = useState("");
  const [activationReasonText, setActivationReasonText] = useState("");
  const [activationChecklistConfirmations, setActivationChecklistConfirmations] =
    useState<Record<string, boolean>>({});
  const [activationWarningsAcknowledged, setActivationWarningsAcknowledged] =
    useState(false);
  const [activationCommitReason, setActivationCommitReason] = useState("");
  const [activationConfirmationText, setActivationConfirmationText] =
    useState("");
  const [
    activationAcknowledgeSameActorWarning,
    setActivationAcknowledgeSameActorWarning,
  ] = useState(false);
  const [activationCommitModalOpen, setActivationCommitModalOpen] =
    useState(false);

  // STEP12-18 — Runtime Registration Review Package & Commit
  const [runtimeRegPackageId, setRuntimeRegPackageId] = useState<
    number | null
  >(null);
  const [runtimeRegAccountKind, setRuntimeRegAccountKind] = useState("PAPER");
  const [runtimeRegAccountId, setRuntimeRegAccountId] = useState<
    number | null
  >(null);
  const [runtimeRegMarketType, setRuntimeRegMarketType] = useState("STOCK");
  const [runtimeRegBrokerCode, setRuntimeRegBrokerCode] = useState("PAPER");
  const [runtimeRegExecutionMode, setRuntimeRegExecutionMode] =
    useState("PAPER");
  const [runtimeRegDecisionType, setRuntimeRegDecisionType] = useState(
    "APPROVE_RUNTIME_REGISTRATION",
  );
  const [runtimeRegReasonCode, setRuntimeRegReasonCode] = useState("");
  const [runtimeRegReasonText, setRuntimeRegReasonText] = useState("");
  const [runtimeRegChecklistConfirmations, setRuntimeRegChecklistConfirmations] =
    useState<Record<string, boolean>>({});
  const [runtimeRegWarningsAcknowledged, setRuntimeRegWarningsAcknowledged] =
    useState(false);
  const [runtimeRegCommitReason, setRuntimeRegCommitReason] = useState("");
  const [runtimeRegConfirmationText, setRuntimeRegConfirmationText] =
    useState("");
  const [
    runtimeRegAcknowledgeSameActorWarning,
    setRuntimeRegAcknowledgeSameActorWarning,
  ] = useState(false);
  const [runtimeRegCommitModalOpen, setRuntimeRegCommitModalOpen] =
    useState(false);

  // STEP12-19 — Runtime Deployment Readiness & Disabled Scheduler Plan
  const [deploySelectedScopeHash, setDeploySelectedScopeHash] = useState<
    string | null
  >(null);
  const [deploySelectedCommitId, setDeploySelectedCommitId] = useState<
    number | null
  >(null);
  const [deploySelectedRegistryId, setDeploySelectedRegistryId] = useState<
    number | null
  >(null);
  const [deployPackageId, setDeployPackageId] = useState<number | null>(null);
  const [deployDecisionType, setDeployDecisionType] = useState(
    "APPROVE_DEPLOYMENT",
  );
  const [deployReasonCode, setDeployReasonCode] = useState("");
  const [deployReasonText, setDeployReasonText] = useState("");
  const [deployChecklistConfirmations, setDeployChecklistConfirmations] =
    useState<Record<string, boolean>>({});
  const [deployWarningsAcknowledged, setDeployWarningsAcknowledged] =
    useState(false);
  const [deployCommitReason, setDeployCommitReason] = useState("");
  const [deployConfirmationText, setDeployConfirmationText] = useState("");
  const [
    deployAcknowledgeSameActorWarning,
    setDeployAcknowledgeSameActorWarning,
  ] = useState(false);
  const [deployCommitModalOpen, setDeployCommitModalOpen] = useState(false);

  // STEP12-20 — Operation Readiness Certification(STEP12 마지막 단계)
  const [opSelectedScopeHash, setOpSelectedScopeHash] = useState<
    string | null
  >(null);
  const [opSelectedDeploymentReadinessCommitId, setOpSelectedDeploymentReadinessCommitId] = useState<
    number | null
  >(null);
  const [opPackageId, setOpPackageId] = useState<number | null>(null);
  const [opDecisionType, setOpDecisionType] = useState("APPROVE_OPERATION");
  const [opReasonCode, setOpReasonCode] = useState("");
  const [opReasonText, setOpReasonText] = useState("");
  const [opChecklistConfirmations, setOpChecklistConfirmations] = useState<
    Record<string, boolean>
  >({});
  const [opWarningsAcknowledged, setOpWarningsAcknowledged] = useState(false);
  const [opCommitReason, setOpCommitReason] = useState("");
  const [opConfirmationText, setOpConfirmationText] = useState("");
  const [opAcknowledgeSameActorWarning, setOpAcknowledgeSameActorWarning] =
    useState(false);
  const [opCommitModalOpen, setOpCommitModalOpen] = useState(false);

  // STEP12-7 — 과거 데이터 Backtest 실행(Admin 전용, 모의 계산 결과)
  const [backtestSymbol, setBacktestSymbol] = useState("");
  const [backtestExchangeCode, setBacktestExchangeCode] = useState("KRX");
  const [backtestStartDate, setBacktestStartDate] = useState("");
  const [backtestEndDate, setBacktestEndDate] = useState("");
  const [backtestInitialCapital, setBacktestInitialCapital] = useState<
    number | null
  >(10_000_000);

  const listParams = {
    strategy_request_id: strategyRequestFilter ?? undefined,
    status: statusFilter || undefined,
    limit: 50,
  };
  const listQuery = useQuery({
    queryKey: queryKeys.admin.strategyDrafts.list(listParams),
    queryFn: () => adminApi.listStrategyDrafts(listParams),
  });
  const items = extractRows(asRecord(listQuery.data)?.items);

  const detailQuery = useQuery({
    queryKey: queryKeys.admin.strategyDrafts.detail(selectedId ?? 0),
    queryFn: () => adminApi.getStrategyDraft(selectedId as number),
    enabled: selectedId != null,
  });
  const detail = asRecord(detailQuery.data) ?? {};

  const historyQuery = useQuery({
    queryKey: queryKeys.admin.strategyDrafts.history(selectedId ?? 0),
    queryFn: () => adminApi.getStrategyDraftHistory(selectedId as number),
    enabled: selectedId != null,
  });
  const historyItems = extractRows(asRecord(historyQuery.data)?.items);

  const versionQuery = useQuery({
    queryKey: queryKeys.admin.strategyDrafts.version(
      versionView?.strategyRequestId ?? 0,
      versionView?.version ?? 0,
    ),
    queryFn: () =>
      adminApi.getStrategyDraftVersion(
        versionView!.strategyRequestId,
        versionView!.version,
      ),
    enabled: versionView != null,
  });
  const versionItems = extractRows(asRecord(versionQuery.data)?.items);

  // STEP12-2-3 — 선택된 Draft가 속한 Strategy Request의 Generation Run들
  // (연결된 Run/Attempt를 찾아 경고 표시에 사용).
  const draftRequestId =
    typeof detail.strategy_request_id === "number"
      ? detail.strategy_request_id
      : undefined;
  const draftGenRunsQuery = useQuery({
    queryKey: queryKeys.admin.strategyDraftGenerations.list({
      strategy_request_id: draftRequestId,
    }),
    queryFn: () =>
      adminApi.listStrategyDraftGenerations({
        strategy_request_id: draftRequestId as number,
        limit: 50,
      }),
    enabled: selectedId != null && draftRequestId != null,
  });
  const draftGenRuns = extractRows(asRecord(draftGenRunsQuery.data)?.items);
  const linkedRun = asRecord(
    draftGenRuns.find((r) => asRecord(r)?.draft_id === selectedId),
  );

  const linkedAttemptsQuery = useQuery({
    queryKey: queryKeys.admin.strategyDraftGenerations.attempts(
      Number(linkedRun?.generation_run_id ?? 0),
    ),
    queryFn: () =>
      adminApi.listStrategyDraftGenerationAttempts(
        Number(linkedRun?.generation_run_id),
      ),
    enabled: linkedRun?.generation_run_id != null,
  });
  const linkedAttempts = extractRows(asRecord(linkedAttemptsQuery.data)?.items);
  const latestAttempt = asRecord(linkedAttempts[linkedAttempts.length - 1]);
  const structuredResponse = asRecord(latestAttempt?.structured_response);

  // 현재 Candidate 상태/fingerprint 조회(조회만 — 변경 없음).
  const liveCandidateQuery = useQuery({
    queryKey: ["admin", "strategy-drafts", "live-candidate-check", draftRequestId ?? 0],
    queryFn: async () => {
      const request = asRecord(
        await adminApi.getStrategyRequest(draftRequestId as number),
      );
      const candidateId = request?.candidate_id;
      if (typeof candidateId !== "number") return null;
      return adminApi.getAiCandidateLifecycle(candidateId);
    },
    enabled: selectedId != null && draftRequestId != null && linkedRun != null,
  });
  const liveLifecycle = asRecord(asRecord(liveCandidateQuery.data)?.lifecycle);

  const comparisonQuery = useQuery({
    queryKey: queryKeys.admin.strategyDraftComparison(
      selectedId ?? 0,
      compareDraftId ?? 0,
    ),
    queryFn: () =>
      adminApi.getStrategyDraftComparison(
        selectedId as number,
        compareDraftId as number,
      ),
    enabled: selectedId != null && compareDraftId != null,
  });
  const comparisonFields = asRecord(
    asRecord(comparisonQuery.data)?.fields,
  );

  const genRunDetailQuery = useQuery({
    queryKey: queryKeys.admin.strategyDraftGenerations.detail(
      genRunDrawerId ?? 0,
    ),
    queryFn: () => adminApi.getStrategyDraftGeneration(genRunDrawerId as number),
    enabled: genRunDrawerId != null,
  });
  const genRunDetail = asRecord(genRunDetailQuery.data) ?? {};
  const genRunAttempts = extractRows(genRunDetail.attempts);

  const timelineQuery = useQuery({
    queryKey: queryKeys.admin.draftTimeline(timelineRequestId ?? 0),
    queryFn: () => adminApi.getDraftTimeline(timelineRequestId as number),
    enabled: timelineRequestId != null,
  });
  const timelineItems = extractRows(asRecord(timelineQuery.data)?.items);

  // STEP12-3 — 이 Draft의 최종 승인 결과(있으면).
  const approvalQuery = useQuery({
    queryKey: queryKeys.admin.strategyDraftApprovals.forDraft(selectedId ?? 0),
    queryFn: () => adminApi.getStrategyDraftApprovalForDraft(selectedId as number),
    enabled: selectedId != null,
  });
  const approval = asRecord(approvalQuery.data);
  const hasApproval = approval != null && Object.keys(approval).length > 0;
  const approvalStatus = hasApproval ? String(approval?.status) : null;

  const approvalHistoryQuery = useQuery({
    queryKey: queryKeys.admin.strategyDraftApprovals.history(
      Number(approval?.approval_id ?? 0),
    ),
    queryFn: () =>
      adminApi.getStrategyDraftApprovalHistory(Number(approval?.approval_id)),
    enabled: hasApproval && approval?.approval_id != null,
  });
  const approvalHistoryItems = extractRows(
    asRecord(approvalHistoryQuery.data)?.items,
  );

  // STEP12-4 — Strategy Snapshot 조회/이력/Diff.
  const snapshotQuery = useQuery({
    queryKey: queryKeys.admin.strategySnapshot.detail(snapshotDrawerId ?? 0),
    queryFn: () => adminApi.getStrategySnapshot(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null,
  });
  const snapshot = asRecord(snapshotQuery.data) ?? {};

  const snapshotHistoryQuery = useQuery({
    queryKey: queryKeys.admin.strategySnapshot.history(snapshotDrawerId ?? 0),
    queryFn: () => adminApi.getStrategySnapshotHistory(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null,
  });
  const snapshotHistoryItems = extractRows(
    asRecord(snapshotHistoryQuery.data)?.items,
  );

  // STEP12-5 — Backtest Readiness / Provenance Chain.
  const readinessQuery = useQuery({
    queryKey: queryKeys.admin.strategyReadiness(snapshotDrawerId ?? 0),
    queryFn: () => adminApi.getStrategyReadiness(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null,
  });
  const readiness = asRecord(readinessQuery.data);
  const readinessChecks = asRecord(readiness?.checks);
  const readinessReasons = extractRows(readiness?.failure_reasons);

  const provenanceQuery = useQuery({
    queryKey: queryKeys.admin.strategyProvenance(snapshotDrawerId ?? 0),
    queryFn: () => adminApi.getStrategyProvenance(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null,
  });
  const provenance = asRecord(provenanceQuery.data);
  const provenanceChain = asRecord(provenance?.chain);
  const provenanceFailures = extractRows(provenance?.failures);

  // STEP12-6 — Backtest Executable Specification(컴파일 진단, 실행 아님).
  const backtestSpecQuery = useQuery({
    queryKey: queryKeys.admin.strategyBacktestSpecification(snapshotDrawerId ?? 0),
    queryFn: () =>
      adminApi.getStrategyBacktestSpecification(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null,
  });
  const backtestSpec = asRecord(backtestSpecQuery.data);

  // STEP12-8 — Backtest 결과 기반 Performance Analytics(KPI + Strategy Score/Grade)
  const performanceQuery = useQuery({
    queryKey: queryKeys.admin.backtestRunPerformance(showPerformanceForRunId ?? 0),
    queryFn: () =>
      adminApi.getBacktestRunPerformance(showPerformanceForRunId as number),
    enabled: showPerformanceForRunId != null,
  });
  const performanceResult = asRecord(performanceQuery.data);
  const performanceKpi = asRecord(performanceResult?.kpi);
  const performanceScore = asRecord(performanceResult?.score);
  const performanceMonthlyReturn = extractRows(performanceKpi?.monthly_return);

  // STEP12-9 — Walk-Forward Analysis(Rolling/Expanding) 조회
  const walkForwardDetailQuery = useQuery({
    queryKey: queryKeys.admin.strategyWalkForward(
      snapshotDrawerId ?? 0,
      walkForwardRunId ?? 0,
    ),
    queryFn: () =>
      adminApi.getStrategyWalkForward(
        snapshotDrawerId as number,
        walkForwardRunId as number,
      ),
    enabled: snapshotDrawerId != null && walkForwardRunId != null,
  });
  const walkForwardOverfittingQuery = useQuery({
    queryKey: queryKeys.admin.strategyWalkForwardOverfitting(
      snapshotDrawerId ?? 0,
      walkForwardRunId ?? 0,
    ),
    queryFn: () =>
      adminApi.getStrategyWalkForwardOverfitting(
        snapshotDrawerId as number,
        walkForwardRunId as number,
      ),
    enabled: snapshotDrawerId != null && walkForwardRunId != null,
  });
  const walkForwardDetail = asRecord(walkForwardDetailQuery.data);
  const walkForwardResultPayload = asRecord(walkForwardDetail?.result_payload);
  const walkForwardWindows = extractRows(walkForwardDetail?.windows);
  const walkForwardOverfitting = asRecord(walkForwardOverfittingQuery.data);

  // STEP12-10 — Strategy Quality Gate 조회
  const qualityGateQuery = useQuery({
    queryKey: queryKeys.admin.strategyQualityGate(
      snapshotDrawerId ?? 0,
      qualityGateReportId ?? 0,
    ),
    queryFn: () =>
      adminApi.getStrategyQualityGate(
        snapshotDrawerId as number,
        qualityGateReportId as number,
      ),
    enabled: snapshotDrawerId != null && qualityGateReportId != null,
  });
  const qualityGateReport = asRecord(qualityGateQuery.data);
  const qualityGateRules = extractRows(qualityGateReport?.rules);

  // STEP12-11 — Parameter Sensitivity Analysis 조회
  const sensitivityQuery = useQuery({
    queryKey: queryKeys.admin.strategyParameterSensitivity(
      snapshotDrawerId ?? 0,
      sensitivityReportId ?? 0,
    ),
    queryFn: () =>
      adminApi.getStrategyParameterSensitivity(
        snapshotDrawerId as number,
        sensitivityReportId as number,
      ),
    enabled: snapshotDrawerId != null && sensitivityReportId != null,
  });
  const sensitivityReport = asRecord(sensitivityQuery.data);
  const sensitivityAnalytics = asRecord(sensitivityReport?.sensitivity_analytics);
  const sensitivityBaseResult = asRecord(sensitivityAnalytics?.base_result);
  const sensitivityStableRange = asRecord(sensitivityReport?.stable_range);
  const sensitivityCliffs = extractRows(sensitivityReport?.performance_cliffs);
  const sensitivityVariations = extractRows(sensitivityReport?.variation_results);

  // STEP12-12 — Monte Carlo Simulation 조회
  const monteCarloQuery = useQuery({
    queryKey: queryKeys.admin.strategyMonteCarlo(
      snapshotDrawerId ?? 0,
      monteCarloReportId ?? 0,
    ),
    queryFn: () =>
      adminApi.getStrategyMonteCarlo(
        snapshotDrawerId as number,
        monteCarloReportId as number,
      ),
    enabled: snapshotDrawerId != null && monteCarloReportId != null,
  });
  const monteCarloReport = asRecord(monteCarloQuery.data);
  const monteCarloPercentiles = asRecord(monteCarloReport?.percentile_payload);
  const monteCarloTotalReturnDist = asRecord(monteCarloPercentiles?.total_return);
  const monteCarloDrawdownDist = asRecord(monteCarloPercentiles?.maximum_drawdown_percent);
  const monteCarloCI = asRecord(monteCarloReport?.confidence_interval_payload);
  const monteCarloReps = asRecord(monteCarloReport?.representative_payload);
  const monteCarloProvenance = asRecord(monteCarloReport?.provenance_payload);

  // STEP12-14 — Strategy Explainability 조회
  const explainabilityQuery = useQuery({
    queryKey: queryKeys.admin.strategyExplainability(
      snapshotDrawerId ?? 0,
      explainabilityReportId ?? 0,
    ),
    queryFn: () =>
      adminApi.getStrategyExplainability(
        snapshotDrawerId as number,
        explainabilityReportId as number,
      ),
    enabled: snapshotDrawerId != null && explainabilityReportId != null,
  });
  const explainabilityReport = asRecord(explainabilityQuery.data);
  const explainOverview = asRecord(explainabilityReport?.strategy_overview);
  const explainRules = asRecord(explainabilityReport?.rule_explanation);
  const explainEntry = asRecord(explainRules?.entry);
  const explainExit = asRecord(explainRules?.exit);
  const explainStopLoss = asRecord(explainRules?.stop_loss);
  const explainTakeProfit = asRecord(explainRules?.take_profit);
  const explainPositionSizing = asRecord(explainRules?.position_sizing);
  const explainBacktest = asRecord(explainabilityReport?.backtest_evidence);
  const explainWalkForward = asRecord(explainabilityReport?.walk_forward_evidence);
  const explainQualityGate = asRecord(explainabilityReport?.quality_gate_evidence);
  const explainSensitivity = asRecord(explainabilityReport?.sensitivity_evidence);
  const explainMonteCarlo = asRecord(explainabilityReport?.monte_carlo_evidence);
  const explainPortfolio = asRecord(explainabilityReport?.portfolio_evidence);
  const explainDecisionSummary = asRecord(explainabilityReport?.decision_summary);
  const explainChecklist = extractRows(explainabilityReport?.decision_checklist);
  const explainEvidenceRefs = extractRows(explainabilityReport?.evidence_reference);
  const explainMissing = extractRows(explainabilityReport?.missing_evidence);

  // STEP12-15 — Decision Package / Human Decision 조회
  const decisionPackageQuery = useQuery({
    queryKey: ["admin", "decision-package", snapshotDrawerId ?? 0, decisionPackageId ?? 0],
    queryFn: () =>
      adminApi.getDecisionPackage(snapshotDrawerId as number, decisionPackageId as number),
    enabled: snapshotDrawerId != null && decisionPackageId != null,
  });
  const decisionPackage = asRecord(decisionPackageQuery.data);
  const decisionChecklistTemplate = extractRows(decisionPackage?.checklist_template);

  const humanDecisionQuery = useQuery({
    queryKey: ["admin", "human-decision", snapshotDrawerId ?? 0, decisionPackageId ?? 0],
    queryFn: () =>
      adminApi.getHumanDecision(snapshotDrawerId as number, decisionPackageId as number),
    enabled: snapshotDrawerId != null && decisionPackageId != null && Boolean(decisionPackage?.has_decision),
  });
  const humanDecision = asRecord(humanDecisionQuery.data);

  const promotionReadinessQuery = useQuery({
    queryKey: ["admin", "promotion-readiness", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getPromotionReadiness(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && Boolean(decisionPackage?.has_decision),
  });
  const promotionReadiness = asRecord(promotionReadinessQuery.data);

  // STEP12-16 — Promotion Status(Promotion Commit 여부 포함)
  const promotionStatusQuery = useQuery({
    queryKey: ["admin", "promotion-status", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getPromotionStatus(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && Boolean(decisionPackage?.has_decision),
  });
  const promotionStatus = asRecord(promotionStatusQuery.data);

  // STEP12-16R — Promotion History(Strategy Promotion State 전이 기록,
  // Candidate Lifecycle과는 별개 축).
  const promotionCommitId =
    typeof promotionStatus?.promotion_commit_id === "number" ? promotionStatus.promotion_commit_id : null;
  const promotionHistoryQuery = useQuery({
    queryKey: ["admin", "promotion-history", snapshotDrawerId ?? 0, promotionCommitId ?? 0],
    queryFn: () => adminApi.getPromotionCommitHistory(snapshotDrawerId as number, promotionCommitId as number),
    enabled: snapshotDrawerId != null && promotionCommitId != null,
  });
  const promotionHistoryItems = extractRows(asRecord(promotionHistoryQuery.data)?.history);

  // STEP12-17 — Activation Review & Activation Commit.
  const activationStatusQuery = useQuery({
    queryKey: ["admin", "activation-status", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getActivationStatus(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && Boolean(promotionStatus?.promotion_committed),
  });
  const activationStatus = asRecord(activationStatusQuery.data);

  const activationPackageQuery = useQuery({
    queryKey: ["admin", "activation-review-package", snapshotDrawerId ?? 0, activationReviewPackageId ?? 0],
    queryFn: () => adminApi.getActivationReviewPackage(snapshotDrawerId as number, activationReviewPackageId as number),
    enabled: snapshotDrawerId != null && activationReviewPackageId != null,
  });
  const activationPackage = asRecord(activationPackageQuery.data);

  const activationChecklistQuery = useQuery({
    queryKey: ["admin", "activation-checklist", snapshotDrawerId ?? 0, activationReviewPackageId ?? 0],
    queryFn: () =>
      adminApi.getActivationReviewPackageChecklist(snapshotDrawerId as number, activationReviewPackageId as number),
    enabled: snapshotDrawerId != null && activationReviewPackageId != null,
  });
  const activationChecklistTemplate = extractRows(asRecord(activationChecklistQuery.data)?.checklist_template);

  const activationDecisionQuery = useQuery({
    queryKey: ["admin", "activation-decision", snapshotDrawerId ?? 0, activationReviewPackageId ?? 0],
    queryFn: () => adminApi.getActivationDecision(snapshotDrawerId as number, activationReviewPackageId as number),
    enabled: snapshotDrawerId != null && activationReviewPackageId != null,
  });
  const activationDecision = asRecord(activationDecisionQuery.data);

  // STEP12-18 — Runtime Registration.
  const runtimeRegStatusQuery = useQuery({
    queryKey: ["admin", "runtime-registration-status", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getRuntimeRegistrationStatus(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && Boolean(activationStatus?.activation_committed),
  });
  const runtimeRegStatus = asRecord(runtimeRegStatusQuery.data);

  // STEP12-19 Carry-forward — 다중 Runtime Scope 목록(동일 Strategy가
  // 여러 Account/User/Execution Mode에 각각 등록될 수 있으므로 단일
  // Status 카드가 아니라 Scope별 Table로 보여준다).
  const runtimeRegScopesQuery = useQuery({
    queryKey: ["admin", "runtime-registration-scopes", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getRuntimeRegistrationScopes(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && Boolean(activationStatus?.activation_committed),
  });
  const runtimeRegScopeItems = extractRows(asRecord(runtimeRegScopesQuery.data)?.scopes);

  const runtimeRegPackageQuery = useQuery({
    queryKey: ["admin", "runtime-registration-package", snapshotDrawerId ?? 0, runtimeRegPackageId ?? 0],
    queryFn: () => adminApi.getRuntimeRegistrationPackage(snapshotDrawerId as number, runtimeRegPackageId as number),
    enabled: snapshotDrawerId != null && runtimeRegPackageId != null,
  });
  const runtimeRegPackage = asRecord(runtimeRegPackageQuery.data);

  const runtimeRegChecklistQuery = useQuery({
    queryKey: ["admin", "runtime-registration-checklist", snapshotDrawerId ?? 0, runtimeRegPackageId ?? 0],
    queryFn: () =>
      adminApi.getRuntimeRegistrationPackageChecklist(snapshotDrawerId as number, runtimeRegPackageId as number),
    enabled: snapshotDrawerId != null && runtimeRegPackageId != null,
  });
  const runtimeRegChecklistTemplate = extractRows(asRecord(runtimeRegChecklistQuery.data)?.checklist_template);

  const runtimeRegDecisionQuery = useQuery({
    queryKey: ["admin", "runtime-registration-decision", snapshotDrawerId ?? 0, runtimeRegPackageId ?? 0],
    queryFn: () => adminApi.getRuntimeRegistrationDecision(snapshotDrawerId as number, runtimeRegPackageId as number),
    enabled: snapshotDrawerId != null && runtimeRegPackageId != null,
  });
  const runtimeRegDecision = asRecord(runtimeRegDecisionQuery.data);

  const runtimeRegHistoryQuery = useQuery({
    queryKey: ["admin", "runtime-registration-history", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getRuntimeRegistrationHistory(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && Boolean(runtimeRegStatus?.registered),
  });
  const runtimeRegHistoryItems = extractRows(asRecord(runtimeRegHistoryQuery.data)?.history);

  // STEP12-19 — Deployment Readiness. REGISTERED(비실행)된 Runtime Scope
  // 각각에 대해 개별적으로 Deployment Readiness를 진행할 수 있어야 하므로,
  // Runtime Registration Scopes 목록과 동일하게 Scope별 Table로 보여준다.
  const deployScopesQuery = useQuery({
    queryKey: ["admin", "deployment-readiness-scopes", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getDeploymentReadinessScopes(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && runtimeRegScopeItems.length > 0,
  });
  const deployScopeItems = extractRows(asRecord(deployScopesQuery.data)?.scopes);
  const deployedScopeHashes = new Set(
    deployScopeItems.map((r) => String(asRecord(r)?.runtime_scope_hash)),
  );

  const deployPackageQuery = useQuery({
    queryKey: ["admin", "deployment-readiness-package", snapshotDrawerId ?? 0, deployPackageId ?? 0],
    queryFn: () => adminApi.getDeploymentReadinessPackage(snapshotDrawerId as number, deployPackageId as number),
    enabled: snapshotDrawerId != null && deployPackageId != null,
  });
  const deployPackage = asRecord(deployPackageQuery.data);

  const deployChecklistQuery = useQuery({
    queryKey: ["admin", "deployment-readiness-checklist", snapshotDrawerId ?? 0, deployPackageId ?? 0],
    queryFn: () =>
      adminApi.getDeploymentReadinessPackageChecklist(snapshotDrawerId as number, deployPackageId as number),
    enabled: snapshotDrawerId != null && deployPackageId != null,
  });
  const deployChecklistTemplate = extractRows(asRecord(deployChecklistQuery.data)?.checklist_template);

  const deployDecisionQuery = useQuery({
    queryKey: ["admin", "deployment-readiness-decision", snapshotDrawerId ?? 0, deployPackageId ?? 0],
    queryFn: () => adminApi.getDeploymentReadinessDecision(snapshotDrawerId as number, deployPackageId as number),
    enabled: snapshotDrawerId != null && deployPackageId != null,
  });
  const deployDecision = asRecord(deployDecisionQuery.data);

  const deployStatusQuery = useQuery({
    queryKey: ["admin", "deployment-readiness-status", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getDeploymentReadinessStatus(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && runtimeRegScopeItems.length > 0,
  });
  const deployStatus = asRecord(deployStatusQuery.data);

  const deployHistoryQuery = useQuery({
    queryKey: ["admin", "deployment-readiness-history", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getDeploymentReadinessHistory(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && Boolean(deployStatus?.deployed),
  });
  const deployHistoryItems = extractRows(asRecord(deployHistoryQuery.data)?.history);

  // STEP12-20 — Operation Readiness Certification. READY_TO_START
  // Deployment(§ deployScopeItems)를 대상으로 한다.
  const opStatusQuery = useQuery({
    queryKey: ["admin", "operation-readiness-status", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getOperationReadinessStatus(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && deployScopeItems.length > 0,
  });
  const opStatus = asRecord(opStatusQuery.data);

  const opCommitsQuery = useQuery({
    queryKey: ["admin", "operation-readiness-commits", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.listOperationReadinessCommits(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && deployScopeItems.length > 0,
  });
  const opCommitItems = extractRows(asRecord(opCommitsQuery.data)?.commits);
  const certifiedScopeHashes = new Set(
    opCommitItems.map((r) => String(asRecord(r)?.runtime_scope_hash)),
  );

  const opPackageQuery = useQuery({
    queryKey: ["admin", "operation-readiness-package", snapshotDrawerId ?? 0, opPackageId ?? 0],
    queryFn: () => adminApi.getOperationReadinessPackage(snapshotDrawerId as number, opPackageId as number),
    enabled: snapshotDrawerId != null && opPackageId != null,
  });
  const opPackage = asRecord(opPackageQuery.data);

  const opCertificationQuery = useQuery({
    queryKey: ["admin", "operation-readiness-certification", snapshotDrawerId ?? 0, opPackageId ?? 0],
    queryFn: () => adminApi.getOperationReadinessCertification(snapshotDrawerId as number, opPackageId as number),
    enabled: snapshotDrawerId != null && opPackageId != null,
  });
  const opCertification = asRecord(opCertificationQuery.data);
  const opCertificationAreas = asRecord(opCertification?.certification_areas) ?? {};

  const opChecklistQuery = useQuery({
    queryKey: ["admin", "operation-readiness-checklist", snapshotDrawerId ?? 0, opPackageId ?? 0],
    queryFn: () => adminApi.getOperationReadinessPackageChecklist(snapshotDrawerId as number, opPackageId as number),
    enabled: snapshotDrawerId != null && opPackageId != null,
  });
  const opChecklistTemplate = extractRows(asRecord(opChecklistQuery.data)?.checklist_template);

  const opDecisionQuery = useQuery({
    queryKey: ["admin", "operation-readiness-decision", snapshotDrawerId ?? 0, opPackageId ?? 0],
    queryFn: () => adminApi.getOperationReadinessDecision(snapshotDrawerId as number, opPackageId as number),
    enabled: snapshotDrawerId != null && opPackageId != null,
  });
  const opDecision = asRecord(opDecisionQuery.data);

  const opHistoryQuery = useQuery({
    queryKey: ["admin", "operation-readiness-history", snapshotDrawerId ?? 0],
    queryFn: () => adminApi.getOperationReadinessHistory(snapshotDrawerId as number),
    enabled: snapshotDrawerId != null && Boolean(opStatus?.certified),
  });
  const opHistoryItems = extractRows(asRecord(opHistoryQuery.data)?.history);

  const backtestIndicatorReqs = extractRows(backtestSpec?.indicator_requirements);
  const backtestRuntimeInputs = extractRows(backtestSpec?.required_runtime_inputs);
  const backtestErrors = extractRows(backtestSpec?.errors);

  // STEP12-11 — 표시용 후보 파라미터 목록(실제 추출/검증은 서버에서 재수행됨).
  const parameterCandidates: string[] = (() => {
    if (!backtestSpec?.compilable) return [];
    const names: string[] = [];
    for (const side of ["entry_rules", "exit_rules"] as const) {
      const rules = extractRows((backtestSpec as Record<string, unknown>)[side]);
      rules.forEach((r, idx) => {
        const rule = asRecord(r);
        if (rule?.lookback != null) names.push(`${side}[${idx}].lookback`);
        names.push(`${side}[${idx}].threshold`);
      });
    }
    names.push("stop_loss_rule.value", "take_profit_rule.value", "position_sizing_rule.value");
    return names;
  })();

  const diffSnapshotQuery = useQuery({
    queryKey: queryKeys.admin.strategySnapshot.detail(diffDefinitionId ?? 0),
    queryFn: () => adminApi.getStrategySnapshot(diffDefinitionId as number),
    enabled: diffDefinitionId != null,
  });
  const diffSnapshot = asRecord(diffSnapshotQuery.data);

  // 간단한 필드 단위 Diff(클라이언트 계산) — 새 API 없이 두 Snapshot의
  // parameter_payload/name/description/market_type만 비교한다.
  const SNAPSHOT_DIFF_FIELDS = [
    "name",
    "description",
    "market_type",
    "definition_version",
  ] as const;
  type SnapshotDiffRow = {
    field: string;
    before: unknown;
    after: unknown;
    status: string;
  };
  const snapshotDiffRows: SnapshotDiffRow[] =
    diffSnapshot == null
      ? []
      : SNAPSHOT_DIFF_FIELDS.map((field): SnapshotDiffRow => {
          const before = snapshot[field];
          const after = diffSnapshot[field];
          const same = JSON.stringify(before) === JSON.stringify(after);
          return { field, before, after, status: same ? "unchanged" : "changed" };
        }).concat(
          (() => {
            const beforePayload = asRecord(snapshot.parameter_payload) ?? {};
            const afterPayload = asRecord(diffSnapshot.parameter_payload) ?? {};
            const keys = new Set([
              ...Object.keys(beforePayload),
              ...Object.keys(afterPayload),
            ]);
            return Array.from(keys).map((key) => {
              const before = beforePayload[key];
              const after = afterPayload[key];
              const same = JSON.stringify(before) === JSON.stringify(after);
              return {
                field: `parameter_payload.${key}`,
                before,
                after,
                status: same ? "unchanged" : "changed",
              };
            });
          })(),
        );

  const generationListQuery = useQuery({
    queryKey: queryKeys.admin.strategyDraftGenerations.list({
      strategy_request_id: genRequestId ?? undefined,
    }),
    queryFn: () =>
      adminApi.listStrategyDraftGenerations({
        strategy_request_id: genRequestId as number,
        limit: 20,
      }),
    enabled: genRequestId != null,
  });
  const generationItems = extractRows(asRecord(generationListQuery.data)?.items);

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "strategy-drafts"],
    });
  };

  const loadEditForm = (d: Record<string, unknown>) => {
    setEditTitle(String(d.title ?? ""));
    setEditSummary(String(d.summary ?? ""));
    setEditEntryRule(String(d.entry_rule ?? ""));
    setEditExitRule(String(d.exit_rule ?? ""));
    setEditReason("");
  };

  const createMutation = useMutation({
    mutationFn: () =>
      adminApi.createStrategyDraft({
        strategy_request_id: newRequestId as number,
        title: newTitle,
        timeframe: newTimeframe,
        market_type: newMarketType,
        summary: newSummary.trim() || undefined,
      }),
    onSuccess: async (result) => {
      const r = asRecord(result);
      message.success(`Draft ${cell(r?.label)} 생성됨`);
      await invalidate();
      if (typeof r?.draft_id === "number") setSelectedId(r.draft_id);
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const reviseMutation = useMutation({
    mutationFn: () =>
      adminApi.createStrategyDraftRevision({
        strategy_request_id: Number(detail.strategy_request_id),
        source_draft_id: selectedId as number,
        reason: editReason.trim() || undefined,
      }),
    onSuccess: async (result) => {
      const r = asRecord(result);
      message.success(`Revision ${cell(r?.label)} 생성됨`);
      await invalidate();
      if (typeof r?.draft_id === "number") setSelectedId(r.draft_id);
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      adminApi.updateStrategyDraft(selectedId as number, {
        title: editTitle.trim() || undefined,
        summary: editSummary.trim() || undefined,
        entry_rule: editEntryRule.trim() || undefined,
        exit_rule: editExitRule.trim() || undefined,
        reason: editReason.trim() || undefined,
      }),
    onSuccess: async () => {
      message.success("Draft를 수정했습니다.");
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const archiveMutation = useMutation({
    mutationFn: (id: number) =>
      adminApi.archiveStrategyDraft(id, {
        reason: editReason.trim() || undefined,
      }),
    onSuccess: async () => {
      message.success("Draft를 Archive했습니다.");
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const isAiGenerated = detail.llm_provider != null;

  // STEP12-2-3 §6 — 안전 경고 표시(조회만, 상태 변경 없음).
  const draftWarnings: string[] = [];
  if (detail.status === "SUPERSEDED") {
    draftWarnings.push("이 Draft는 새 Version 생성으로 대체(SUPERSEDED)되었습니다.");
  }
  if (detail.status === "ARCHIVED") {
    draftWarnings.push("이 Draft는 Archive되었습니다.");
  }
  if (isAiGenerated) {
    draftWarnings.push(
      "AI가 생성한 Draft입니다 — 직접 수정할 수 없으며 Revision 생성만 가능합니다.",
    );
  }
  if (detail.llm_provider === "mock") {
    draftWarnings.push(
      "Mock Provider로 생성된 결과입니다 — 실 Provider 검증을 거치지 않았습니다.",
    );
  }
  if (typeof linkedRun?.retry_number === "number" && linkedRun.retry_number > 0) {
    draftWarnings.push(`재시도(Retry #${linkedRun.retry_number})로 생성된 결과입니다.`);
  }
  if (
    draftGenRuns.some((r) => {
      const s = asRecord(r)?.status;
      return s === "FAILED" || s === "TIMED_OUT";
    })
  ) {
    draftWarnings.push("이 Strategy Request에 이전 Generation 실패 이력이 있습니다.");
  }
  if (
    typeof structuredResponse?.confidence === "number" &&
    structuredResponse.confidence < 0.5
  ) {
    draftWarnings.push(`Confidence가 낮습니다(${structuredResponse.confidence}).`);
  }
  if (
    Array.isArray(structuredResponse?.warnings) &&
    structuredResponse.warnings.length > 0
  ) {
    draftWarnings.push(
      `Validation warning 존재: ${structuredResponse.warnings.join(", ")}`,
    );
  }
  if (
    Array.isArray(structuredResponse?.assumptions) &&
    structuredResponse.assumptions.length > 0
  ) {
    draftWarnings.push(
      `Assumption 존재: ${structuredResponse.assumptions.join(", ")}`,
    );
  }
  if (
    liveLifecycle &&
    linkedRun &&
    liveLifecycle.lifecycle_status !== linkedRun.candidate_lifecycle_status_at_request
  ) {
    draftWarnings.push(
      `Candidate 상태가 생성 시점(${String(linkedRun.candidate_lifecycle_status_at_request)})과 다릅니다(현재: ${String(liveLifecycle.lifecycle_status)}).`,
    );
  }
  if (
    liveLifecycle &&
    linkedRun &&
    liveLifecycle.source_fingerprint !== linkedRun.candidate_fingerprint_at_request
  ) {
    draftWarnings.push("Candidate fingerprint가 생성 시점과 다릅니다.");
  }

  // STEP12-3 §14 — 화면 표시용 승인 가능 여부 추정(서버가 항상 다시
  // 전체 검증한다 — 이 목록은 사용자 안내용일 뿐 최종 판단이 아니다).
  const approvalBlockedReasons: string[] = [];
  if (detail.status !== "DRAFT") {
    approvalBlockedReasons.push(
      `Draft 상태가 ${cell(detail.status)}입니다(DRAFT만 승인 가능).`,
    );
  }
  if (hasApproval && approvalStatus === "APPROVED") {
    approvalBlockedReasons.push("이미 승인된 Draft입니다.");
  }
  if (
    liveLifecycle &&
    liveLifecycle.lifecycle_status !== "PROMOTED" &&
    liveLifecycle.lifecycle_status !== "ACTIVE_REVIEW"
  ) {
    approvalBlockedReasons.push(
      `Candidate 상태가 ACTIVE가 아닙니다(현재: ${String(liveLifecycle.lifecycle_status)}).`,
    );
  }
  if (
    liveLifecycle &&
    detail.candidate_fingerprint != null &&
    liveLifecycle.source_fingerprint !== detail.candidate_fingerprint
  ) {
    approvalBlockedReasons.push("Candidate fingerprint가 Draft 생성 시점과 다릅니다.");
  }
  if (isAiGenerated && linkedRun != null && linkedRun.status !== "SUCCEEDED") {
    approvalBlockedReasons.push(
      `연결된 Generation Run이 SUCCEEDED가 아닙니다(현재: ${String(linkedRun.status)}).`,
    );
  }
  const canAttemptApproval =
    detail.status === "DRAFT" && !(hasApproval && approvalStatus === "APPROVED");

  const invalidateApprovals = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "strategy-draft-approvals"],
    });
  };

  const approveMutation = useMutation({
    mutationFn: () =>
      adminApi.approveStrategyDraft(selectedId as number, {
        reason: approveReason.trim(),
      }),
    onSuccess: async (result) => {
      const r = asRecord(result);
      message.success(
        `승인 완료 — Strategy Definition #${cell(r?.strategy_definition_id)}`,
      );
      setApproveReason("");
      await invalidateApprovals();
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const rejectMutation = useMutation({
    mutationFn: () =>
      adminApi.rejectStrategyDraft(selectedId as number, {
        reason: rejectReason.trim(),
      }),
    onSuccess: async () => {
      message.success("반려했습니다.");
      setRejectReason("");
      await invalidateApprovals();
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const revokeMutation = useMutation({
    mutationFn: () =>
      adminApi.revokeStrategyDraftApproval(Number(approval?.approval_id), {
        reason: revokeReason.trim(),
      }),
    onSuccess: async () => {
      message.success("승인을 취소했습니다.");
      setRevokeReason("");
      await invalidateApprovals();
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const runBacktestMutation = useMutation({
    mutationFn: () =>
      adminApi.runStrategyBacktest(snapshotDrawerId as number, {
        symbol: backtestSymbol.trim().toUpperCase(),
        exchange_code: backtestExchangeCode.trim().toUpperCase(),
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        initial_capital: String(backtestInitialCapital ?? 0),
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      if (r?.idempotent_replay) {
        message.info("동일 idempotency_key로 이전에 실행된 결과를 반환했습니다.");
      } else {
        message.success(
          "과거 데이터 Backtest 실행이 완료됐습니다(모의 계산 결과 — 실거래와 다를 수 있음).",
        );
      }
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const runWalkForwardMutation = useMutation({
    mutationFn: () =>
      adminApi.runStrategyWalkForward(snapshotDrawerId as number, {
        symbol: backtestSymbol.trim().toUpperCase(),
        exchange_code: backtestExchangeCode.trim().toUpperCase(),
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        train_days: walkForwardTrainDays ?? 0,
        test_days: walkForwardTestDays ?? 0,
        window_scheme: walkForwardScheme,
        initial_capital: String(backtestInitialCapital ?? 0),
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const runId = Number(r?.strategy_performance_run_id);
      if (runId) setWalkForwardRunId(runId);
      message.success(
        "Walk-Forward 분석이 완료됐습니다(모의 계산 결과 — 실거래와 다를 수 있음).",
      );
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const runQualityGateMutation = useMutation({
    mutationFn: () => adminApi.runStrategyQualityGate(snapshotDrawerId as number),
    onSuccess: (result) => {
      const r = asRecord(result);
      const reportId = Number(r?.quality_gate_report_id);
      if (reportId) setQualityGateReportId(reportId);
      message.success("Quality Gate 심사가 완료됐습니다.");
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const runParameterSensitivityMutation = useMutation({
    mutationFn: () =>
      adminApi.runStrategyParameterSensitivity(snapshotDrawerId as number, {
        symbol: backtestSymbol.trim().toUpperCase(),
        exchange_code: backtestExchangeCode.trim().toUpperCase(),
        start_date: backtestStartDate,
        end_date: backtestEndDate,
        initial_capital: String(backtestInitialCapital ?? 0),
        parameter_names: sensitivityParameterNames,
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const reportId = Number(r?.parameter_sensitivity_report_id);
      if (reportId) setSensitivityReportId(reportId);
      message.success(
        "Parameter Sensitivity 분석이 완료됐습니다(최고 수익 파라미터 자동 선택 아님).",
      );
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const runMonteCarloMutation = useMutation({
    mutationFn: () =>
      adminApi.runStrategyMonteCarlo(snapshotDrawerId as number, {
        backtest_run_id: monteCarloBacktestRunId as number,
        simulation_method: monteCarloMethod,
        simulation_count: monteCarloCount ?? undefined,
        random_seed: monteCarloSeed ?? undefined,
        confidence_level: monteCarloConfidenceLevel,
        ruin_threshold_percent: String(monteCarloRuinThreshold ?? 50),
        block_size: monteCarloBlockSize ?? undefined,
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const reportId = Number(r?.report_id);
      if (reportId) setMonteCarloReportId(reportId);
      message.success(
        "Monte Carlo Simulation이 완료됐습니다(미래 수익을 보장하지 않는 확률적 재표본화 결과입니다).",
      );
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const runExplainabilityMutation = useMutation({
    mutationFn: () =>
      adminApi.runStrategyExplainability(snapshotDrawerId as number, {
        backtest_run_id: explainBacktestRunId ?? undefined,
        quality_gate_report_id: explainQualityGateReportId ?? undefined,
        parameter_sensitivity_report_id: explainSensitivityReportId ?? undefined,
        monte_carlo_report_id: explainMonteCarloReportId ?? undefined,
        use_latest_when_missing: explainUseLatestWhenMissing,
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const reportId = Number(r?.report_id);
      if (reportId) setExplainabilityReportId(reportId);
      message.success(
        "Explainability Report가 생성됐습니다(자동 승인/투자 권고가 아닙니다).",
      );
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createDecisionPackageMutation = useMutation({
    mutationFn: () =>
      adminApi.createDecisionPackage(snapshotDrawerId as number, {
        explainability_report_id: explainabilityReportId as number,
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const packageId = Number(r?.package_id);
      if (packageId) setDecisionPackageId(packageId);
      setChecklistConfirmations({});
      message.success("Decision Package가 생성됐습니다(Strategy 상태는 변경되지 않습니다).");
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const recordHumanDecisionMutation = useMutation({
    mutationFn: () =>
      adminApi.recordHumanDecision(snapshotDrawerId as number, decisionPackageId as number, {
        decision_type: decisionType,
        reason_code: reasonCode,
        reason_text: reasonText,
        checklist_confirmations: checklistConfirmations,
        acknowledged_warnings: warningsAcknowledged ? ["ALL"] : [],
      }),
    onSuccess: () => {
      message.success(
        "결정이 기록됐습니다. 실제 Promotion Commit은 실행되지 않으며, 별도의 명시적 Commit 단계가 필요합니다.",
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "human-decision"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "decision-package"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "promotion-readiness"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createPromotionCommitMutation = useMutation({
    mutationFn: () =>
      adminApi.createPromotionCommit(snapshotDrawerId as number, {
        decision_package_id: decisionPackageId as number,
        human_decision_id: Number(humanDecision?.decision_id),
        promotion_readiness_hash: String(humanDecision?.promotion_readiness_hash ?? ""),
        commit_reason: commitReason,
        confirmation_text: confirmationText,
        acknowledge_same_actor_warning: acknowledgeSameActorWarning,
      }),
    onSuccess: () => {
      message.success(
        "Promotion Commit이 생성됐습니다(Activation/Deployment/Runtime 등록은 수행되지 않았습니다).",
      );
      setPromotionCommitModalOpen(false);
      queryClient.invalidateQueries({ queryKey: ["admin", "promotion-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "promotion-readiness"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createActivationReviewPackageMutation = useMutation({
    mutationFn: () =>
      adminApi.createActivationReviewPackage(snapshotDrawerId as number, {
        promotion_commit_id: Number(promotionStatus?.promotion_commit_id),
        target_market_type: activationTargetMarketType,
        target_broker_code: activationTargetBrokerCode,
        target_account_kind: activationTargetAccountKind,
        target_user_broker_account_id:
          activationTargetAccountKind === "USER_BROKER" ? activationTargetAccountId ?? undefined : undefined,
        target_paper_account_id:
          activationTargetAccountKind === "PAPER" ? activationTargetAccountId ?? undefined : undefined,
        requested_execution_mode: activationExecutionMode,
        review_note: activationReviewNote || undefined,
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const packageId = Number(r?.activation_review_package_id);
      if (packageId) setActivationReviewPackageId(packageId);
      setActivationChecklistConfirmations({});
      message.success(
        `Activation Review Package가 생성됐습니다(readiness: ${String(r?.readiness_status ?? "")}). Runtime/Scheduler/Broker 연결은 수행되지 않았습니다.`,
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "activation-status"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const recordActivationDecisionMutation = useMutation({
    mutationFn: () =>
      adminApi.recordActivationDecision(snapshotDrawerId as number, activationReviewPackageId as number, {
        decision_type: activationDecisionType,
        reason_code: activationReasonCode,
        reason_text: activationReasonText,
        checklist_confirmations: activationChecklistConfirmations,
        acknowledged_warnings: activationWarningsAcknowledged ? ["ALL"] : [],
      }),
    onSuccess: () => {
      message.success(
        "Activation Decision이 기록됐습니다. 실제 Activation Commit은 실행되지 않으며, 별도의 명시적 Commit 단계가 필요합니다.",
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "activation-decision"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createActivationCommitMutation = useMutation({
    mutationFn: () =>
      adminApi.createActivationCommit(snapshotDrawerId as number, {
        activation_review_package_id: activationReviewPackageId as number,
        activation_decision_id: Number(activationDecision?.activation_decision_id),
        activation_readiness_hash: String(activationDecision?.decision_input_hash ?? ""),
        commit_reason: activationCommitReason,
        confirmation_text: activationConfirmationText,
        acknowledge_same_actor_warning: activationAcknowledgeSameActorWarning,
      }),
    onSuccess: () => {
      message.success(
        "Activation Commit이 생성됐습니다(Runtime, Scheduler, Broker 연결 또는 주문 실행은 수행되지 않았습니다).",
      );
      setActivationCommitModalOpen(false);
      queryClient.invalidateQueries({ queryKey: ["admin", "activation-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "promotion-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "promotion-history"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createRuntimeRegistrationPackageMutation = useMutation({
    mutationFn: () =>
      adminApi.createRuntimeRegistrationPackage(snapshotDrawerId as number, {
        activation_commit_id: Number(activationStatus?.activation_commit_id),
        activation_decision_id: Number(activationDecision?.activation_decision_id),
        target_account_kind: runtimeRegAccountKind,
        target_user_broker_account_id:
          runtimeRegAccountKind === "USER_BROKER" ? runtimeRegAccountId ?? undefined : undefined,
        target_paper_account_id: runtimeRegAccountKind === "PAPER" ? runtimeRegAccountId ?? undefined : undefined,
        target_market_type: runtimeRegMarketType,
        target_broker_code: runtimeRegBrokerCode,
        execution_mode: runtimeRegExecutionMode,
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const packageId = Number(r?.runtime_registration_package_id);
      if (packageId) setRuntimeRegPackageId(packageId);
      setRuntimeRegChecklistConfirmations({});
      message.success(
        `Runtime Registration Package가 생성됐습니다(readiness: ${String(r?.registration_readiness_status ?? "")}). Runtime은 시작되지 않았습니다.`,
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "runtime-registration-status"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const recordRuntimeRegistrationDecisionMutation = useMutation({
    mutationFn: () =>
      adminApi.recordRuntimeRegistrationDecision(snapshotDrawerId as number, runtimeRegPackageId as number, {
        decision_type: runtimeRegDecisionType,
        reason_code: runtimeRegReasonCode,
        reason_text: runtimeRegReasonText,
        checklist_confirmations: runtimeRegChecklistConfirmations,
        acknowledged_warnings: runtimeRegWarningsAcknowledged ? ["ALL"] : [],
      }),
    onSuccess: () => {
      message.success(
        "Runtime Registration Decision이 기록됐습니다. 실제 Registration Commit은 실행되지 않으며, 별도의 명시적 Commit 단계가 필요합니다.",
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "runtime-registration-decision"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createRuntimeRegistrationCommitMutation = useMutation({
    mutationFn: () =>
      adminApi.createRuntimeRegistrationCommit(snapshotDrawerId as number, {
        runtime_registration_package_id: runtimeRegPackageId as number,
        runtime_registration_decision_id: Number(runtimeRegDecision?.runtime_registration_decision_id),
        registration_input_hash: String(runtimeRegPackage?.registration_input_hash ?? ""),
        decision_input_hash: String(runtimeRegDecision?.decision_input_hash ?? ""),
        commit_reason: runtimeRegCommitReason,
        confirmation_text: runtimeRegConfirmationText,
        acknowledge_same_actor_warning: runtimeRegAcknowledgeSameActorWarning,
      }),
    onSuccess: () => {
      message.success(
        "Runtime Registration Commit이 생성됐습니다(Runtime, Scheduler, Broker 연결, 실시간 시세 구독 또는 주문 생성/전송은 수행되지 않았습니다).",
      );
      setRuntimeRegCommitModalOpen(false);
      queryClient.invalidateQueries({ queryKey: ["admin", "runtime-registration-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "runtime-registration-history"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createDeploymentReadinessPackageMutation = useMutation({
    mutationFn: () =>
      adminApi.createDeploymentReadinessPackage(snapshotDrawerId as number, {
        runtime_registration_commit_id: deploySelectedCommitId as number,
        runtime_registry_id: deploySelectedRegistryId as number,
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const packageId = Number(r?.deployment_readiness_package_id);
      if (packageId) setDeployPackageId(packageId);
      setDeployChecklistConfirmations({});
      message.success(
        `Deployment Readiness Package가 생성됐습니다(readiness: ${String(r?.readiness_status ?? "")}). Runtime은 시작되지 않았습니다.`,
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "deployment-readiness-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "deployment-readiness-scopes"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const recordDeploymentReadinessDecisionMutation = useMutation({
    mutationFn: () =>
      adminApi.recordDeploymentReadinessDecision(snapshotDrawerId as number, deployPackageId as number, {
        decision_type: deployDecisionType,
        reason_code: deployReasonCode,
        reason_text: deployReasonText,
        checklist_confirmations: deployChecklistConfirmations,
        acknowledged_warnings: deployWarningsAcknowledged ? ["ALL"] : [],
      }),
    onSuccess: () => {
      message.success(
        "Deployment Readiness Decision이 기록됐습니다. 실제 Deployment Commit은 실행되지 않으며, 별도의 명시적 Commit 단계가 필요합니다.",
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "deployment-readiness-decision"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createDeploymentReadinessCommitMutation = useMutation({
    mutationFn: () =>
      adminApi.createDeploymentReadinessCommit(snapshotDrawerId as number, {
        deployment_readiness_package_id: deployPackageId as number,
        deployment_readiness_decision_id: Number(deployDecision?.deployment_readiness_decision_id),
        runtime_registration_commit_id: deploySelectedCommitId as number,
        runtime_scope_hash: deploySelectedScopeHash as string,
        deployment_input_hash: String(deployPackage?.deployment_input_hash ?? ""),
        decision_input_hash: String(deployDecision?.decision_input_hash ?? ""),
        commit_reason: deployCommitReason,
        confirmation_text: deployConfirmationText,
        acknowledge_same_actor_warning: deployAcknowledgeSameActorWarning,
      }),
    onSuccess: () => {
      message.success(
        "Deployment Readiness Commit이 생성됐습니다(READY_TO_START). Runtime, Scheduler, Broker 연결, 실시간 시세 구독 또는 주문 생성/전송은 수행되지 않았습니다. 실제 자동매매 시작은 별도 STEP13 승인이 필요합니다.",
      );
      setDeployCommitModalOpen(false);
      queryClient.invalidateQueries({ queryKey: ["admin", "deployment-readiness-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "deployment-readiness-history"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "deployment-readiness-scopes"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createOperationReadinessPackageMutation = useMutation({
    mutationFn: () =>
      adminApi.createOperationReadinessPackage(snapshotDrawerId as number, {
        deployment_readiness_commit_id: opSelectedDeploymentReadinessCommitId as number,
      }),
    onSuccess: (result) => {
      const r = asRecord(result);
      const packageId = Number(r?.operation_readiness_package_id);
      if (packageId) setOpPackageId(packageId);
      setOpChecklistConfirmations({});
      message.success(
        `Operation Readiness Package가 생성됐습니다(readiness: ${String(r?.readiness_status ?? "")}). Runtime은 시작되지 않았습니다.`,
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "operation-readiness-status"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const recordOperationReadinessDecisionMutation = useMutation({
    mutationFn: () =>
      adminApi.recordOperationReadinessDecision(snapshotDrawerId as number, opPackageId as number, {
        decision_type: opDecisionType,
        reason_code: opReasonCode,
        reason_text: opReasonText,
        checklist_confirmations: opChecklistConfirmations,
        acknowledged_warnings: opWarningsAcknowledged ? ["ALL"] : [],
      }),
    onSuccess: () => {
      message.success(
        "Operation Readiness Decision이 기록됐습니다. 실제 Operation Commit은 실행되지 않으며, 별도의 명시적 Commit 단계가 필요합니다.",
      );
      queryClient.invalidateQueries({ queryKey: ["admin", "operation-readiness-decision"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const createOperationReadinessCommitMutation = useMutation({
    mutationFn: () =>
      adminApi.createOperationReadinessCommit(snapshotDrawerId as number, {
        operation_readiness_package_id: opPackageId as number,
        operation_readiness_decision_id: Number(opDecision?.operation_readiness_decision_id),
        deployment_readiness_commit_id: opSelectedDeploymentReadinessCommitId as number,
        runtime_scope_hash: opSelectedScopeHash as string,
        operation_input_hash: String(opPackage?.operation_input_hash ?? ""),
        decision_input_hash: String(opDecision?.decision_input_hash ?? ""),
        commit_reason: opCommitReason,
        confirmation_text: opConfirmationText,
        acknowledge_same_actor_warning: opAcknowledgeSameActorWarning,
      }),
    onSuccess: () => {
      message.success(
        "Operation Readiness Commit이 생성됐습니다(READY_TO_OPERATE). Runtime, Scheduler, Broker 연결, 실시간 시세 구독 또는 주문 생성/전송은 수행되지 않았습니다. 실제 자동매매 시작(START)은 별도 STEP13 승인이 필요합니다.",
      );
      setOpCommitModalOpen(false);
      queryClient.invalidateQueries({ queryKey: ["admin", "operation-readiness-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "operation-readiness-history"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "deployment-readiness-scopes"] });
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const invalidateGenerations = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "strategy-draft-generations"],
    });
  };

  const generateMutation = useMutation({
    mutationFn: () =>
      adminApi.createStrategyDraftGeneration({
        strategy_request_id: genRequestId as number,
      }),
    onSuccess: async (result) => {
      const r = asRecord(result);
      const run = asRecord(r?.run) ?? r;
      if (run?.status === "SUCCEEDED") {
        message.success("AI Draft 생성 완료");
      } else {
        message.warning(
          `AI Draft 생성 실패: ${String(run?.error_code ?? run?.status ?? "")}`,
        );
      }
      await invalidateGenerations();
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  const retryGenerationMutation = useMutation({
    mutationFn: (runId: number) => adminApi.retryStrategyDraftGeneration(runId),
    onSuccess: async () => {
      message.success("재시도를 요청했습니다.");
      await invalidateGenerations();
      await invalidate();
    },
    onError: (error) => message.error(toApiError(error).message),
  });

  return (
    <AdminPageShell
      title="Strategy Draft 관리"
      extra={
        <Link href={adminRoutes.portfolioValidations}>
          <Button>Portfolio Validation →</Button>
        </Link>
      }
    >
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Alert
          type="warning"
          showIcon
          title="이 화면은 승인된 Strategy Request 위에 Draft를 저장·버전관리하는 기반 구조입니다. AI 생성, Backtest, 실거래 승인, Runtime 등록을 의미하지 않습니다."
        />

        <Space wrap align="start">
          <Space direction="vertical" size={4}>
            <Typography.Text type="secondary">필터</Typography.Text>
            <Space>
              <InputNumber
                placeholder="Strategy Request ID"
                value={strategyRequestFilter ?? undefined}
                onChange={(v) =>
                  setStrategyRequestFilter(typeof v === "number" ? v : null)
                }
                style={{ width: 180 }}
              />
              <Select
                style={{ width: 160 }}
                value={statusFilter}
                onChange={setStatusFilter}
                options={STATUS_OPTIONS}
              />
            </Space>
          </Space>

          <Space direction="vertical" size={4}>
            <Typography.Text type="secondary">새 Draft(새 Version) 생성</Typography.Text>
            <Space wrap>
              <InputNumber
                placeholder="Strategy Request ID"
                value={newRequestId ?? undefined}
                onChange={(v) => setNewRequestId(typeof v === "number" ? v : null)}
                style={{ width: 160 }}
              />
              <Input
                placeholder="제목"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                style={{ width: 160 }}
              />
              <Input
                placeholder="Timeframe(예: 1D)"
                value={newTimeframe}
                onChange={(e) => setNewTimeframe(e.target.value)}
                style={{ width: 120 }}
              />
              <Input
                placeholder="Market Type"
                value={newMarketType}
                onChange={(e) => setNewMarketType(e.target.value)}
                style={{ width: 120 }}
              />
              <Input
                placeholder="요약(선택)"
                value={newSummary}
                onChange={(e) => setNewSummary(e.target.value)}
                style={{ width: 200 }}
              />
              <Button
                type="primary"
                loading={createMutation.isPending}
                disabled={!newRequestId || !newTitle}
                onClick={() => createMutation.mutate()}
              >
                생성
              </Button>
            </Space>
          </Space>
        </Space>

        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            title="AI Draft 생성 결과는 검토 전 초안입니다. 자동 승인·Backtest·Paper Trading·Runtime 등록·실주문으로 연결되지 않습니다."
          />
          <Space wrap align="start">
            <Typography.Text type="secondary">AI Strategy Draft 생성</Typography.Text>
            <InputNumber
              placeholder="Strategy Request ID"
              value={genRequestId ?? undefined}
              onChange={(v) => setGenRequestId(typeof v === "number" ? v : null)}
              style={{ width: 160 }}
            />
            <Button
              type="primary"
              loading={generateMutation.isPending}
              disabled={!genRequestId || generateMutation.isPending}
              onClick={() => generateMutation.mutate()}
            >
              AI로 생성
            </Button>
          </Space>
          {genRequestId != null && (
            <Space orientation="vertical" size={4} style={{ width: "100%" }}>
              <Typography.Link
                onClick={() => setTimelineRequestId(genRequestId)}
              >
                Draft + Generation Timeline 보기
              </Typography.Link>
              <Table
                size="small"
                loading={generationListQuery.isLoading}
                dataSource={generationItems}
                rowKey={(r) => String(asRecord(r)?.generation_run_id)}
                pagination={false}
                onRow={(r) => ({
                  onClick: (e) => {
                    // 재시도 버튼 클릭까지 행 클릭으로 처리되지 않도록 방지.
                    if ((e.target as HTMLElement).closest("button")) return;
                    const id = asRecord(r)?.generation_run_id;
                    if (typeof id === "number") setGenRunDrawerId(id);
                  },
                })}
                columns={[
                {
                  title: "Run",
                  dataIndex: "generation_run_id",
                  width: 70,
                  render: cell,
                },
                {
                  title: "상태",
                  dataIndex: "status",
                  width: 110,
                  render: (v: string) => (
                    <Tag
                      color={
                        v === "SUCCEEDED"
                          ? "success"
                          : v === "FAILED" || v === "TIMED_OUT"
                            ? "error"
                            : "processing"
                      }
                    >
                      {v}
                    </Tag>
                  ),
                },
                { title: "Provider", dataIndex: "provider", width: 90, render: cell },
                { title: "Model", dataIndex: "model", width: 110, render: cell },
                { title: "Draft", dataIndex: "draft_id", width: 80, render: cell },
                { title: "오류", dataIndex: "error_code", render: cell },
                {
                  title: "",
                  key: "actions",
                  width: 90,
                  render: (_: unknown, r) => {
                    const row = asRecord(r);
                    const runId = row?.generation_run_id;
                    const isTerminalFailure =
                      row?.status === "FAILED" || row?.status === "TIMED_OUT";
                    return isTerminalFailure && typeof runId === "number" ? (
                      <Button
                        size="small"
                        loading={retryGenerationMutation.isPending}
                        onClick={() => retryGenerationMutation.mutate(runId)}
                      >
                        재시도
                      </Button>
                    ) : null;
                  },
                },
              ]}
              />
            </Space>
          )}
        </Space>

        <Table
          size="small"
          loading={listQuery.isLoading}
          dataSource={items}
          rowKey={(r) => String(asRecord(r)?.draft_id)}
          pagination={{ pageSize: 10 }}
          onRow={(r) => ({
            onClick: () => {
              const row = asRecord(r);
              const id = row?.draft_id;
              if (typeof id === "number") {
                setSelectedId(id);
                loadEditForm(row ?? {});
              }
            },
          })}
          columns={[
            { title: "ID", dataIndex: "draft_id", width: 70, render: cell },
            { title: "Version", dataIndex: "label", width: 100, render: cell },
            {
              title: "Request",
              dataIndex: "strategy_request_id",
              width: 90,
              render: cell,
            },
            {
              title: "상태",
              dataIndex: "status",
              width: 130,
              render: (v: string) => (
                <Tag color={STATUS_COLOR[v] ?? "default"}>{v}</Tag>
              ),
            },
            { title: "제목", dataIndex: "title", render: cell },
            { title: "생성일시", dataIndex: "created_at", render: cell },
          ]}
        />

        {listQuery.isError && (
          <Alert type="error" title={toApiError(listQuery.error).message} />
        )}
      </Space>

      <Drawer
        title={selectedId != null ? `Strategy Draft #${selectedId}` : "상세"}
        open={selectedId != null}
        onClose={() => setSelectedId(null)}
        size={640}
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
              <Tag>{cell(detail.label)}</Tag>
              <Typography.Link
                onClick={() =>
                  setVersionView({
                    strategyRequestId: Number(detail.strategy_request_id),
                    version: Number(detail.version),
                  })
                }
              >
                이 Version 전체 보기
              </Typography.Link>
            </Space>

            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Strategy Request">
                {cell(detail.strategy_request_id)}
              </Descriptions.Item>
              <Descriptions.Item label="제목">{cell(detail.title)}</Descriptions.Item>
              <Descriptions.Item label="요약">
                {cell(detail.summary)}
              </Descriptions.Item>
              <Descriptions.Item label="Timeframe / Market">
                {cell(detail.timeframe)} / {cell(detail.market_type)}
              </Descriptions.Item>
              <Descriptions.Item label="Entry Rule">
                {cell(detail.entry_rule)}
              </Descriptions.Item>
              <Descriptions.Item label="Exit Rule">
                {cell(detail.exit_rule)}
              </Descriptions.Item>
              <Descriptions.Item label="Stop Loss / Take Profit">
                {cell(detail.stop_loss_rule)} / {cell(detail.take_profit_rule)}
              </Descriptions.Item>
              <Descriptions.Item label="Position Sizing">
                {cell(detail.position_sizing_rule)}
              </Descriptions.Item>
              <Descriptions.Item label="Candidate Fingerprint">
                {cell(detail.candidate_fingerprint)}
              </Descriptions.Item>
              <Descriptions.Item label="생성자 / 생성일시">
                {cell(detail.created_by)} · {cell(detail.created_at)}
              </Descriptions.Item>
            </Descriptions>

            {draftWarnings.length > 0 && (
              <Alert
                type="warning"
                showIcon
                title="검토 시 주의"
                description={
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {draftWarnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                }
              />
            )}

            {isAiGenerated && (
              <Typography.Link
                onClick={() =>
                  linkedRun?.generation_run_id != null &&
                  setGenRunDrawerId(Number(linkedRun.generation_run_id))
                }
              >
                {linkedRun?.generation_run_id != null
                  ? `Generation Run #${linkedRun.generation_run_id} 상세 보기`
                  : "연결된 Generation Run 없음"}
              </Typography.Link>
            )}

            <Typography.Title level={5}>최종 승인</Typography.Title>
            {hasApproval ? (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag
                    color={
                      approvalStatus === "APPROVED"
                        ? "success"
                        : approvalStatus === "REJECTED"
                          ? "error"
                          : approvalStatus === "REVOKED"
                            ? "default"
                            : "warning"
                    }
                  >
                    {approvalStatus}
                  </Tag>
                  {approval?.strategy_definition_id != null && (
                    <Typography.Link
                      onClick={() =>
                        setSnapshotDrawerId(Number(approval.strategy_definition_id))
                      }
                    >
                      Strategy Definition #{cell(approval.strategy_definition_id)} Snapshot 보기
                    </Typography.Link>
                  )}
                </Space>
                <Descriptions size="small" column={1} bordered>
                  <Descriptions.Item label="결정자 / 사유">
                    {cell(approval?.decided_by)} · {cell(approval?.reason)}
                  </Descriptions.Item>
                  <Descriptions.Item label="결정 시각">
                    {cell(approval?.decided_at)}
                  </Descriptions.Item>
                  {approval?.revoked_at != null && (
                    <Descriptions.Item label="취소자 / 사유 / 시각">
                      {cell(approval.revoked_by)} · {cell(approval.revoked_reason)} ·{" "}
                      {cell(approval.revoked_at)}
                    </Descriptions.Item>
                  )}
                </Descriptions>
                {approvalStatus === "APPROVED" && (
                  <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                    <Input
                      placeholder="승인 취소 사유(필수)"
                      value={revokeReason}
                      onChange={(e) => setRevokeReason(e.target.value)}
                    />
                    <Button
                      danger
                      loading={revokeMutation.isPending}
                      disabled={!revokeReason.trim() || revokeMutation.isPending}
                      onClick={() => revokeMutation.mutate()}
                    >
                      승인 취소(Revoke)
                    </Button>
                  </Space>
                )}
                <Typography.Title level={5}>Approval History</Typography.Title>
                {approvalHistoryItems.length === 0 ? (
                  <Empty description="이력 없음" />
                ) : (
                  <Table
                    size="small"
                    dataSource={approvalHistoryItems}
                    rowKey={(r) => String(asRecord(r)?.history_id)}
                    pagination={false}
                    columns={[
                      { title: "Action", dataIndex: "action", render: cell },
                      { title: "From", dataIndex: "previous_status", render: cell },
                      { title: "To", dataIndex: "new_status", render: cell },
                      { title: "Actor", dataIndex: "actor", render: cell },
                      { title: "사유", dataIndex: "reason", render: cell },
                      { title: "At", dataIndex: "created_at", render: cell },
                    ]}
                  />
                )}
              </Space>
            ) : (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                {approvalBlockedReasons.length > 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    title="승인 불가 사유(표시용 — 서버가 항상 다시 전체 검증합니다)"
                    description={
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {approvalBlockedReasons.map((r) => (
                          <li key={r}>{r}</li>
                        ))}
                      </ul>
                    }
                  />
                )}
                <Input
                  placeholder="승인 사유(필수)"
                  value={approveReason}
                  onChange={(e) => setApproveReason(e.target.value)}
                />
                <Input
                  placeholder="반려 사유(필수)"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                />
                <Space wrap>
                  <Button
                    type="primary"
                    loading={approveMutation.isPending}
                    disabled={
                      !canAttemptApproval ||
                      !approveReason.trim() ||
                      approveMutation.isPending ||
                      rejectMutation.isPending
                    }
                    onClick={() => approveMutation.mutate()}
                  >
                    승인(Approve)
                  </Button>
                  <Button
                    danger
                    loading={rejectMutation.isPending}
                    disabled={
                      !canAttemptApproval ||
                      !rejectReason.trim() ||
                      approveMutation.isPending ||
                      rejectMutation.isPending
                    }
                    onClick={() => rejectMutation.mutate()}
                  >
                    반려(Reject)
                  </Button>
                </Space>
              </Space>
            )}

            {detail.status === "DRAFT" && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Title level={5}>
                  편집{isAiGenerated ? "(AI 생성 — Revision만 가능)" : "(DRAFT만 가능)"}
                </Typography.Title>
                {!isAiGenerated && (
                  <>
                    <Input
                      placeholder="제목"
                      value={editTitle}
                      onChange={(e) => setEditTitle(e.target.value)}
                    />
                    <Input.TextArea
                      rows={2}
                      placeholder="요약"
                      value={editSummary}
                      onChange={(e) => setEditSummary(e.target.value)}
                    />
                    <Input.TextArea
                      rows={2}
                      placeholder="Entry Rule"
                      value={editEntryRule}
                      onChange={(e) => setEditEntryRule(e.target.value)}
                    />
                    <Input.TextArea
                      rows={2}
                      placeholder="Exit Rule"
                      value={editExitRule}
                      onChange={(e) => setEditExitRule(e.target.value)}
                    />
                  </>
                )}
                <Input
                  placeholder="변경/Archive 사유(선택)"
                  value={editReason}
                  onChange={(e) => setEditReason(e.target.value)}
                />
                <Space wrap>
                  {!isAiGenerated && (
                    <Button
                      type="primary"
                      loading={updateMutation.isPending}
                      onClick={() => updateMutation.mutate()}
                    >
                      수정 저장
                    </Button>
                  )}
                  <Button
                    loading={reviseMutation.isPending}
                    onClick={() => reviseMutation.mutate()}
                  >
                    Revision 생성
                  </Button>
                  <Button
                    danger
                    loading={archiveMutation.isPending}
                    onClick={() =>
                      selectedId != null && archiveMutation.mutate(selectedId)
                    }
                  >
                    Archive
                  </Button>
                </Space>
              </Space>
            )}
            {detail.status !== "DRAFT" && detail.status !== "ARCHIVED" && (
              <Button
                danger
                loading={archiveMutation.isPending}
                onClick={() =>
                  selectedId != null && archiveMutation.mutate(selectedId)
                }
              >
                Archive
              </Button>
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

            <Typography.Title level={5}>Version/Revision 비교</Typography.Title>
            <Space wrap>
              <InputNumber
                placeholder="비교할 Draft ID"
                value={compareDraftId ?? undefined}
                onChange={(v) => setCompareDraftId(typeof v === "number" ? v : null)}
                style={{ width: 180 }}
              />
            </Space>
            {compareDraftId != null && comparisonFields && (
              <Table
                size="small"
                loading={comparisonQuery.isLoading}
                dataSource={Object.entries(comparisonFields).map(([field, value]) => ({
                  field,
                  ...(asRecord(value) ?? {}),
                }))}
                rowKey="field"
                pagination={false}
                columns={[
                  { title: "필드", dataIndex: "field", width: 160 },
                  {
                    title: "상태",
                    dataIndex: "status",
                    width: 100,
                    render: (v: string) => (
                      <Tag
                        color={
                          v === "changed"
                            ? "warning"
                            : v === "added"
                              ? "success"
                              : v === "removed"
                                ? "error"
                                : "default"
                        }
                      >
                        {v}
                      </Tag>
                    ),
                  },
                  { title: "이전(A)", dataIndex: "before", render: cell },
                  { title: "이후(B)", dataIndex: "after", render: cell },
                ]}
              />
            )}
            {comparisonQuery.isError && (
              <Alert
                type="error"
                title={toApiError(comparisonQuery.error).message}
              />
            )}
          </Space>
        )}
      </Drawer>

      <Drawer
        title={
          genRunDrawerId != null
            ? `Generation Run #${genRunDrawerId}`
            : "Generation Run"
        }
        open={genRunDrawerId != null}
        onClose={() => setGenRunDrawerId(null)}
        size={560}
        destroyOnHidden
      >
        {genRunDetailQuery.isLoading ? (
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        ) : (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Space wrap>
              <Tag
                color={
                  genRunDetail.status === "SUCCEEDED"
                    ? "success"
                    : genRunDetail.status === "FAILED" ||
                        genRunDetail.status === "TIMED_OUT"
                      ? "error"
                      : "processing"
                }
              >
                {String(genRunDetail.status ?? "")}
              </Tag>
              {genRunDetail.provider === "mock" && (
                <Tag color="warning">Mock Provider</Tag>
              )}
            </Space>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="Strategy Request">
                {cell(genRunDetail.strategy_request_id)}
              </Descriptions.Item>
              <Descriptions.Item label="Candidate">
                {cell(genRunDetail.candidate_id)}
              </Descriptions.Item>
              <Descriptions.Item label="Provider / Model">
                {cell(genRunDetail.provider)} / {cell(genRunDetail.model)}
              </Descriptions.Item>
              <Descriptions.Item label="Retry Number">
                {cell(genRunDetail.retry_number)}
              </Descriptions.Item>
              <Descriptions.Item label="Candidate 상태 스냅샷">
                {cell(genRunDetail.candidate_lifecycle_status_at_request)}
              </Descriptions.Item>
              <Descriptions.Item label="Candidate Fingerprint 스냅샷">
                {cell(genRunDetail.candidate_fingerprint_at_request)}
              </Descriptions.Item>
              <Descriptions.Item label="연결된 Draft">
                {cell(genRunDetail.draft_id)}
              </Descriptions.Item>
              <Descriptions.Item label="시작 / 종료">
                {cell(genRunDetail.started_at)} · {cell(genRunDetail.completed_at)}
              </Descriptions.Item>
              <Descriptions.Item label="오류">
                {cell(genRunDetail.error_code)} — {cell(genRunDetail.error_message)}
              </Descriptions.Item>
            </Descriptions>

            <Typography.Title level={5}>Attempts</Typography.Title>
            <Table
              size="small"
              dataSource={genRunAttempts}
              rowKey={(r) => String(asRecord(r)?.generation_attempt_id)}
              pagination={false}
              columns={[
                { title: "#", dataIndex: "attempt_no", width: 40, render: cell },
                { title: "상태", dataIndex: "status", width: 100, render: cell },
                {
                  title: "Tokens",
                  dataIndex: "total_tokens",
                  width: 80,
                  render: cell,
                },
                {
                  title: "Latency(ms)",
                  dataIndex: "latency_ms",
                  width: 100,
                  render: cell,
                },
                {
                  title: "Prompt Hash",
                  dataIndex: "prompt_hash",
                  render: (v: string) => cell(v ? `${v.slice(0, 12)}…` : v),
                },
                { title: "오류", dataIndex: "error_code", render: cell },
              ]}
            />
          </Space>
        )}
      </Drawer>

      <Drawer
        title={
          timelineRequestId != null
            ? `Strategy Request #${timelineRequestId} Timeline`
            : "Timeline"
        }
        open={timelineRequestId != null}
        onClose={() => setTimelineRequestId(null)}
        size={520}
        destroyOnHidden
      >
        <Table
          size="small"
          loading={timelineQuery.isLoading}
          dataSource={timelineItems}
          rowKey={(r, idx) => `${asRecord(r)?.type}-${idx}`}
          pagination={false}
          columns={[
            { title: "구분", dataIndex: "type", render: cell },
            { title: "Action", dataIndex: "action", render: cell },
            { title: "Draft", dataIndex: "draft_id", render: cell },
            { title: "Run", dataIndex: "generation_run_id", render: cell },
            { title: "시각", dataIndex: "occurred_at", render: cell },
          ]}
        />
      </Drawer>

      <Drawer
        title={
          versionView
            ? `Strategy Request #${versionView.strategyRequestId} — v${versionView.version} Revision 목록`
            : "Version"
        }
        open={versionView != null}
        onClose={() => setVersionView(null)}
        size={520}
        destroyOnHidden
      >
        <Table
          size="small"
          loading={versionQuery.isLoading}
          dataSource={versionItems}
          rowKey={(r) => String(asRecord(r)?.draft_id)}
          pagination={false}
          onRow={(r) => ({
            onClick: () => {
              const id = asRecord(r)?.draft_id;
              if (typeof id === "number") {
                setVersionView(null);
                setSelectedId(id);
              }
            },
          })}
          columns={[
            { title: "Revision", dataIndex: "label", render: cell },
            {
              title: "상태",
              dataIndex: "status",
              render: (v: string) => (
                <Tag color={STATUS_COLOR[v] ?? "default"}>{v}</Tag>
              ),
            },
            { title: "생성일시", dataIndex: "created_at", render: cell },
          ]}
        />
      </Drawer>

      <Drawer
        title={
          snapshotDrawerId != null
            ? `Strategy Definition #${snapshotDrawerId} Snapshot`
            : "Snapshot"
        }
        open={snapshotDrawerId != null}
        onClose={() => {
          setSnapshotDrawerId(null);
          setDiffDefinitionId(null);
        }}
        size={640}
        destroyOnHidden
      >
        {snapshotQuery.isLoading ? (
          <Typography.Text type="secondary">불러오는 중…</Typography.Text>
        ) : (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Space wrap>
              <Tag color={snapshot.hash_valid ? "success" : "error"}>
                {snapshot.hash_valid ? "Hash 검증됨" : "Hash 불일치(변조 의심)"}
              </Tag>
              <Tag>Version {cell(snapshot.definition_version)}</Tag>
              <Tag color={snapshot.is_active ? "processing" : "default"}>
                {snapshot.is_active ? "활성" : "비활성"}
              </Tag>
            </Space>
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label="이름">{cell(snapshot.name)}</Descriptions.Item>
              <Descriptions.Item label="설명">
                {cell(snapshot.description)}
              </Descriptions.Item>
              <Descriptions.Item label="Market Type">
                {cell(snapshot.market_type)}
              </Descriptions.Item>
              <Descriptions.Item label="Definition Hash">
                {cell(snapshot.definition_hash)}
              </Descriptions.Item>
              <Descriptions.Item label="Source Draft">
                #{cell(snapshot.source_draft_id)} (v{cell(snapshot.source_draft_version)}
                -r{cell(snapshot.source_draft_revision)})
              </Descriptions.Item>
              <Descriptions.Item label="Strategy Request / Candidate">
                {cell(snapshot.strategy_request_id)} / {cell(snapshot.candidate_id)}
              </Descriptions.Item>
              <Descriptions.Item label="Candidate Fingerprint">
                {cell(snapshot.candidate_fingerprint)}
              </Descriptions.Item>
              <Descriptions.Item label="Approval ID">
                {cell(snapshot.approval_id)}
              </Descriptions.Item>
              <Descriptions.Item label="승인자 / 승인일시">
                {cell(snapshot.approved_by)} · {cell(snapshot.approved_at)}
              </Descriptions.Item>
            </Descriptions>
            {snapshot.hash_valid === false && (
              <Alert
                type="error"
                showIcon
                title="저장된 definition_hash가 현재 내용과 일치하지 않습니다. Export가 차단됩니다."
              />
            )}

            <Typography.Title level={5}>Backtest Readiness</Typography.Title>
            {readinessQuery.isLoading ? (
              <Typography.Text type="secondary">확인 중…</Typography.Text>
            ) : (
              <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                <Tag color={readiness?.ready ? "success" : "error"}>
                  {readiness?.ready ? "Backtest Ready" : "Not Ready"}
                </Tag>
                {readinessChecks && (
                  <Space wrap>
                    {Object.entries(readinessChecks).map(([key, value]) => (
                      <Tag key={key} color={value ? "success" : "error"}>
                        {key}: {String(value)}
                      </Tag>
                    ))}
                  </Space>
                )}
                {readinessReasons.length > 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    title="Readiness 실패 사유"
                    description={
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {readinessReasons.map((r, idx) => (
                          <li key={idx}>{String(r)}</li>
                        ))}
                      </ul>
                    }
                  />
                )}
              </Space>
            )}

            <Typography.Title level={5}>Provenance Chain</Typography.Title>
            {provenanceQuery.isLoading ? (
              <Typography.Text type="secondary">확인 중…</Typography.Text>
            ) : (
              <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                <Tag color={provenance?.valid ? "success" : "error"}>
                  {provenance?.valid ? "Chain Valid" : "Chain Invalid"}
                </Tag>
                {provenanceChain && (
                  <Descriptions size="small" column={1} bordered>
                    <Descriptions.Item label="Candidate → Draft → Approval → Definition">
                      #{cell(provenanceChain.candidate_id)} → #
                      {cell(provenanceChain.source_draft_id)} → #
                      {cell(provenanceChain.approval_id)} → #
                      {cell(provenanceChain.strategy_definition_id)}
                    </Descriptions.Item>
                    <Descriptions.Item label="Generation Run / Attempt">
                      {cell(provenanceChain.generation_run_id)} /{" "}
                      {cell(provenanceChain.generation_attempt_id)}
                    </Descriptions.Item>
                  </Descriptions>
                )}
                {provenanceFailures.length > 0 && (
                  <Alert
                    type="error"
                    showIcon
                    title="Provenance Chain 불일치"
                    description={
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {provenanceFailures.map((f, idx) => (
                          <li key={idx}>{String(f)}</li>
                        ))}
                      </ul>
                    }
                  />
                )}
              </Space>
            )}

            <Typography.Title level={5}>Backtest 입력 검증(실행 아님)</Typography.Title>
            {backtestSpecQuery.isLoading ? (
              <Typography.Text type="secondary">확인 중…</Typography.Text>
            ) : (
              <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color={backtestSpec?.compilable ? "success" : "error"}>
                    {backtestSpec?.compilable
                      ? "Backtest 입력 생성 가능"
                      : "Backtest 입력 생성 불가"}
                  </Tag>
                  <Tag>Compiler v{cell(backtestSpec?.compiler_version)}</Tag>
                </Space>
                {backtestSpec?.executable_hash != null && (
                  <Typography.Text code style={{ fontSize: 12 }}>
                    executable_hash: {String(backtestSpec.executable_hash)}
                  </Typography.Text>
                )}
                {backtestIndicatorReqs.length > 0 && (
                  <Space direction="vertical" size={2}>
                    <Typography.Text type="secondary">필요 Indicator</Typography.Text>
                    <Space wrap>
                      {backtestIndicatorReqs.map((r, idx) => {
                        const row = asRecord(r);
                        return (
                          <Tag key={idx}>
                            {cell(row?.indicator)}({cell(row?.period)})
                          </Tag>
                        );
                      })}
                    </Space>
                  </Space>
                )}
                {backtestRuntimeInputs.length > 0 && (
                  <Space direction="vertical" size={2}>
                    <Typography.Text type="secondary">
                      실행 시 필요한 Runtime 입력(Definition에는 없음 — 실행 요청 시
                      주입 필요)
                    </Typography.Text>
                    <Space wrap>
                      {backtestRuntimeInputs.map((r, idx) => {
                        const row = asRecord(r);
                        return (
                          <Tag key={idx} color={row?.required ? "processing" : "default"}>
                            {cell(row?.name)}: {cell(row?.type)}
                          </Tag>
                        );
                      })}
                    </Space>
                  </Space>
                )}
                {backtestErrors.length > 0 && (
                  <Alert
                    type="warning"
                    showIcon
                    title="Backtest 입력 생성 실패 사유"
                    description={
                      <ul style={{ margin: 0, paddingLeft: 18 }}>
                        {backtestErrors.map((e, idx) => (
                          <li key={idx}>{String(e)}</li>
                        ))}
                      </ul>
                    }
                  />
                )}
              </Space>
            )}

            <Typography.Title level={5}>과거 데이터 Backtest 실행</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              모의 계산 결과이며 실거래와 다를 수 있습니다. 실제 계좌/주문과는
              무관합니다.
            </Typography.Text>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Space wrap>
                <Input
                  placeholder="종목 코드(symbol)"
                  value={backtestSymbol}
                  onChange={(e) => setBacktestSymbol(e.target.value)}
                  style={{ width: 160 }}
                />
                <Input
                  placeholder="거래소(exchange_code)"
                  value={backtestExchangeCode}
                  onChange={(e) => setBacktestExchangeCode(e.target.value)}
                  style={{ width: 140 }}
                />
                <Input
                  placeholder="시작일(YYYY-MM-DD)"
                  value={backtestStartDate}
                  onChange={(e) => setBacktestStartDate(e.target.value)}
                  style={{ width: 160 }}
                />
                <Input
                  placeholder="종료일(YYYY-MM-DD)"
                  value={backtestEndDate}
                  onChange={(e) => setBacktestEndDate(e.target.value)}
                  style={{ width: 160 }}
                />
                <InputNumber
                  placeholder="초기자본금"
                  value={backtestInitialCapital ?? undefined}
                  onChange={(v) =>
                    setBacktestInitialCapital(typeof v === "number" ? v : null)
                  }
                  min={1}
                  style={{ width: 160 }}
                />
              </Space>
              <Button
                type="primary"
                loading={runBacktestMutation.isPending}
                disabled={
                  runBacktestMutation.isPending ||
                  !backtestSymbol.trim() ||
                  !backtestExchangeCode.trim() ||
                  !backtestStartDate ||
                  !backtestEndDate ||
                  !readiness?.ready
                }
                onClick={() => runBacktestMutation.mutate()}
              >
                과거 데이터 Backtest 실행
              </Button>
              {(() => {
                const backtestResult = asRecord(runBacktestMutation.data);
                if (!backtestResult) return null;
                const backtestSummary = asRecord(backtestResult.summary);
                return (
                  <Descriptions size="small" column={1} bordered>
                    <Descriptions.Item label="상태">
                      {cell(backtestResult.status)}
                    </Descriptions.Item>
                    <Descriptions.Item label="거래 횟수">
                      {cell(backtestSummary?.trade_count)}
                    </Descriptions.Item>
                    <Descriptions.Item label="수익률(모의 계산)">
                      {cell(backtestSummary?.total_return_rate)}%
                    </Descriptions.Item>
                    <Descriptions.Item label="최대 낙폭(MDD)">
                      {cell(backtestSummary?.maximum_drawdown_rate)}%
                    </Descriptions.Item>
                    <Descriptions.Item label="최종 평가금액">
                      {cell(backtestSummary?.final_equity)}
                    </Descriptions.Item>
                  </Descriptions>
                );
              })()}
              {runBacktestMutation.data != null &&
                (() => {
                  const backtestRunId = Number(
                    asRecord(runBacktestMutation.data)?.backtest_run_id,
                  );
                  if (!backtestRunId) return null;
                  return (
                    <Button
                      size="small"
                      onClick={() => setShowPerformanceForRunId(backtestRunId)}
                    >
                      성과 분석 보기(Strategy Score)
                    </Button>
                  );
                })()}
            </Space>

            {showPerformanceForRunId != null && (
              <>
                <Typography.Title level={5}>
                  Performance Analytics — Backtest #{showPerformanceForRunId}
                </Typography.Title>
                {performanceQuery.isLoading ? (
                  <Typography.Text type="secondary">분석 중…</Typography.Text>
                ) : (
                  <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                    <Space wrap>
                      <Tag
                        color={
                          performanceScore?.grade === "A+" ||
                          performanceScore?.grade === "A"
                            ? "success"
                            : performanceScore?.grade === "F"
                              ? "error"
                              : "processing"
                        }
                      >
                        Strategy Score:{" "}
                        {performanceScore?.score != null
                          ? `${cell(performanceScore.score)} (${cell(performanceScore.grade)})`
                          : "계산 불가(데이터 부족)"}
                      </Tag>
                    </Space>
                    <Descriptions size="small" column={2} bordered>
                      <Descriptions.Item label="Total Return">
                        {cell(performanceKpi?.total_return_rate)}%
                      </Descriptions.Item>
                      <Descriptions.Item label="CAGR">
                        {cell(performanceKpi?.cagr)}%
                      </Descriptions.Item>
                      <Descriptions.Item label="Sharpe Ratio">
                        {cell(performanceKpi?.sharpe_ratio)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Sortino Ratio">
                        {cell(performanceKpi?.sortino_ratio)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Calmar Ratio">
                        {cell(performanceKpi?.calmar_ratio)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Profit Factor">
                        {cell(performanceKpi?.profit_factor)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Recovery Factor">
                        {cell(performanceKpi?.recovery_factor)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Expectancy">
                        {cell(performanceKpi?.expectancy)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Maximum Drawdown">
                        {cell(performanceKpi?.maximum_drawdown_rate)}%
                      </Descriptions.Item>
                      <Descriptions.Item label="Ulcer Index">
                        {cell(performanceKpi?.ulcer_index)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Win Rate">
                        {cell(performanceKpi?.win_rate)}%
                      </Descriptions.Item>
                      <Descriptions.Item label="Average Holding Days">
                        {cell(performanceKpi?.average_holding_days)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Consecutive Wins / Losses">
                        {cell(performanceKpi?.consecutive_wins)} /{" "}
                        {cell(performanceKpi?.consecutive_losses)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Trade Count(Long)">
                        {cell(performanceKpi?.trade_count)}
                      </Descriptions.Item>
                    </Descriptions>
                    {performanceMonthlyReturn.length > 0 && (
                      <Table
                        size="small"
                        dataSource={performanceMonthlyReturn}
                        rowKey={(r) => String(asRecord(r)?.period)}
                        pagination={false}
                        columns={[
                          {
                            title: "Month",
                            dataIndex: "period",
                            render: (_, r: unknown) => cell(asRecord(r)?.period),
                          },
                          {
                            title: "Return",
                            render: (_, r: unknown) => (
                              <>{cell(asRecord(r)?.return_rate)}%</>
                            ),
                          },
                        ]}
                      />
                    )}
                  </Space>
                )}
              </>
            )}

            <Typography.Title level={5}>Walk-Forward Analysis</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              In-Sample(학습)/Out-of-Sample(검증) 구간을 자동 분리해 반복
              실행한 모의 계산 결과이며 실거래와 다를 수 있습니다.
            </Typography.Text>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Space wrap>
                <InputNumber
                  placeholder="Train Days"
                  value={walkForwardTrainDays ?? undefined}
                  onChange={(v) =>
                    setWalkForwardTrainDays(typeof v === "number" ? v : null)
                  }
                  min={1}
                  style={{ width: 140 }}
                />
                <InputNumber
                  placeholder="Test Days"
                  value={walkForwardTestDays ?? undefined}
                  onChange={(v) =>
                    setWalkForwardTestDays(typeof v === "number" ? v : null)
                  }
                  min={1}
                  style={{ width: 140 }}
                />
                <Select
                  value={walkForwardScheme}
                  onChange={(v) =>
                    setWalkForwardScheme(v as "ROLLING" | "EXPANDING")
                  }
                  style={{ width: 160 }}
                  options={[
                    { value: "ROLLING", label: "Rolling Window" },
                    { value: "EXPANDING", label: "Expanding Window" },
                  ]}
                />
              </Space>
              <Button
                loading={runWalkForwardMutation.isPending}
                disabled={
                  runWalkForwardMutation.isPending ||
                  !backtestSymbol.trim() ||
                  !backtestExchangeCode.trim() ||
                  !backtestStartDate ||
                  !backtestEndDate ||
                  !walkForwardTrainDays ||
                  !walkForwardTestDays ||
                  !readiness?.ready
                }
                onClick={() => runWalkForwardMutation.mutate()}
              >
                Walk-Forward 실행
              </Button>

              {walkForwardRunId != null && (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  <Space wrap>
                    <Tag
                      color={
                        walkForwardResultPayload?.overfitting_grade === "HIGH"
                          ? "error"
                          : walkForwardResultPayload?.overfitting_grade === "MEDIUM"
                            ? "warning"
                            : "success"
                      }
                    >
                      Overfitting: {cell(walkForwardResultPayload?.overfitting_grade)} (
                      {cell(walkForwardOverfitting?.overfitting_score)})
                    </Tag>
                    <Tag>
                      Stability Score:{" "}
                      {cell(
                        asRecord(walkForwardResultPayload?.stability)?.stability_score,
                      )}
                    </Tag>
                    <Tag>Consistency Score: {cell(walkForwardResultPayload?.consistency_score)}</Tag>
                    <Tag>Success Ratio: {cell(walkForwardResultPayload?.success_ratio)}%</Tag>
                    <Tag>Forward Performance: {cell(walkForwardResultPayload?.forward_performance)}%</Tag>
                  </Space>
                  <Table
                    size="small"
                    loading={walkForwardDetailQuery.isLoading}
                    dataSource={walkForwardWindows}
                    rowKey={(r) => String(asRecord(r)?.window_no)}
                    pagination={false}
                    columns={[
                      { title: "Window", dataIndex: "window_no", render: cell },
                      { title: "Test 시작", dataIndex: "test_start_date", render: cell },
                      { title: "Test 종료", dataIndex: "test_end_date", render: cell },
                      {
                        title: "수익률(Out)",
                        render: (_, r: unknown) => (
                          <>{cell(asRecord(r)?.total_return_rate)}%</>
                        ),
                      },
                      {
                        title: "MDD(Out)",
                        render: (_, r: unknown) => (
                          <>{cell(asRecord(r)?.maximum_drawdown_rate)}%</>
                        ),
                      },
                      { title: "Sharpe(Out)", dataIndex: "sharpe_ratio", render: cell },
                      { title: "거래 수(Out)", dataIndex: "total_trade_count", render: cell },
                    ]}
                  />
                </Space>
              )}
            </Space>

            <Typography.Title level={5}>Strategy Quality Gate</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              기존 Backtest/Walk-Forward 결과만 재사용한 자동 품질 심사이며
              실거래 승인을 의미하지 않습니다.
            </Typography.Text>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Button
                loading={runQualityGateMutation.isPending}
                disabled={runQualityGateMutation.isPending || !readiness?.ready}
                onClick={() => runQualityGateMutation.mutate()}
              >
                Quality Gate 실행
              </Button>

              {qualityGateReportId != null && (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {qualityGateQuery.isLoading ? (
                    <Typography.Text type="secondary">확인 중…</Typography.Text>
                  ) : (
                    <>
                      <Space wrap>
                        <Tag
                          color={
                            qualityGateReport?.recommendation === "APPROVE"
                              ? "success"
                              : qualityGateReport?.recommendation === "REJECT"
                                ? "error"
                                : "warning"
                          }
                        >
                          Recommendation: {cell(qualityGateReport?.recommendation)}
                        </Tag>
                        <Tag
                          color={
                            qualityGateReport?.risk_grade === "SAFE"
                              ? "success"
                              : qualityGateReport?.risk_grade === "NORMAL"
                                ? "processing"
                                : qualityGateReport?.risk_grade === "CAUTION"
                                  ? "warning"
                                  : "error"
                          }
                        >
                          Risk Grade: {cell(qualityGateReport?.risk_grade)}
                        </Tag>
                      </Space>
                      <Table
                        size="small"
                        dataSource={qualityGateRules}
                        rowKey={(r) => String(asRecord(r)?.rule_name)}
                        pagination={false}
                        columns={[
                          { title: "Rule", dataIndex: "rule_name", render: cell },
                          {
                            title: "실제값",
                            render: (_, r: unknown) => cell(asRecord(r)?.actual_value),
                          },
                          {
                            title: "Threshold",
                            render: (_, r: unknown) =>
                              cell(JSON.stringify(asRecord(r)?.threshold)),
                          },
                          {
                            title: "상태",
                            dataIndex: "status",
                            render: (v: string) => (
                              <Tag
                                color={
                                  v === "PASS"
                                    ? "success"
                                    : v === "WARNING"
                                      ? "warning"
                                      : "error"
                                }
                              >
                                {v}
                              </Tag>
                            ),
                          },
                          {
                            title: "Failure Reason",
                            dataIndex: "failure_reason",
                            render: cell,
                          },
                        ]}
                      />
                    </>
                  )}
                </Space>
              )}
            </Space>

            <Typography.Title level={5}>Parameter Sensitivity Analysis</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              기준 파라미터 주변의 성과 안정성만 검증합니다 — 최고 수익
              파라미터를 자동으로 찾거나 적용하지 않습니다. 최대 2개 파라미터,
              조합 최대 25개까지만 지원합니다.
            </Typography.Text>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Select
                mode="multiple"
                placeholder="분석할 파라미터 선택(최대 2개)"
                value={sensitivityParameterNames}
                onChange={(values) =>
                  setSensitivityParameterNames((values as string[]).slice(-2))
                }
                options={parameterCandidates.map((name) => ({
                  value: name,
                  label: name,
                }))}
                style={{ width: "100%" }}
                disabled={parameterCandidates.length === 0}
              />
              <Button
                loading={runParameterSensitivityMutation.isPending}
                disabled={
                  runParameterSensitivityMutation.isPending ||
                  sensitivityParameterNames.length === 0 ||
                  !backtestSymbol.trim() ||
                  !backtestExchangeCode.trim() ||
                  !backtestStartDate ||
                  !backtestEndDate ||
                  !readiness?.ready
                }
                onClick={() => runParameterSensitivityMutation.mutate()}
              >
                Parameter Sensitivity 분석 실행
              </Button>

              {sensitivityReportId != null && (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {sensitivityQuery.isLoading ? (
                    <Typography.Text type="secondary">분석 중…</Typography.Text>
                  ) : (
                    <>
                      <Space wrap>
                        <Tag
                          color={
                            sensitivityReport?.sensitivity_status === "ROBUST"
                              ? "success"
                              : sensitivityReport?.sensitivity_status === "FRAGILE"
                                ? "error"
                                : sensitivityReport?.sensitivity_status ===
                                    "INSUFFICIENT_DATA"
                                  ? "default"
                                  : "warning"
                          }
                        >
                          Sensitivity: {cell(sensitivityReport?.sensitivity_status)}
                        </Tag>
                        <Tag>
                          Robustness Score: {cell(sensitivityReport?.robustness_score)}
                        </Tag>
                        <Tag>
                          Stable Range:{" "}
                          {sensitivityStableRange?.includes_base
                            ? `${cell(sensitivityStableRange?.min_value)} ~ ${cell(sensitivityStableRange?.max_value)}`
                            : "없음(불안정)"}
                        </Tag>
                      </Space>
                      {sensitivityBaseResult && (
                        <Descriptions size="small" column={2} bordered title="기준값 결과">
                          <Descriptions.Item label="Total Return">
                            {cell(sensitivityBaseResult.total_return_rate)}%
                          </Descriptions.Item>
                          <Descriptions.Item label="Sharpe">
                            {cell(sensitivityBaseResult.sharpe_ratio)}
                          </Descriptions.Item>
                          <Descriptions.Item label="MDD">
                            {cell(sensitivityBaseResult.maximum_drawdown_rate)}%
                          </Descriptions.Item>
                          <Descriptions.Item label="Strategy Score">
                            {cell(sensitivityBaseResult.strategy_score)} (
                            {cell(sensitivityBaseResult.grade)})
                          </Descriptions.Item>
                        </Descriptions>
                      )}
                      {sensitivityCliffs.length > 0 && (
                        <Alert
                          type="warning"
                          showIcon
                          title="Performance Cliff 감지됨"
                          description={
                            <ul style={{ margin: 0, paddingLeft: 18 }}>
                              {sensitivityCliffs.map((c, idx) => {
                                const cliff = asRecord(c);
                                return (
                                  <li key={idx}>
                                    {cell(cliff?.cliff_parameter_from)} →{" "}
                                    {cell(cliff?.cliff_parameter_to)}:{" "}
                                    {cell(cliff?.cliff_reason)} (
                                    {cell(cliff?.severity)})
                                  </li>
                                );
                              })}
                            </ul>
                          }
                        />
                      )}
                      <Table
                        size="small"
                        dataSource={sensitivityVariations}
                        rowKey={(r) => String(asRecord(r)?.combination_no)}
                        pagination={false}
                        columns={[
                          {
                            title: "Parameters",
                            render: (_, r: unknown) =>
                              cell(JSON.stringify(asRecord(r)?.parameter_values)),
                          },
                          {
                            title: "상태",
                            dataIndex: "status",
                            render: (v: string) => (
                              <Tag color={v === "SUCCESS" ? "success" : "error"}>{v}</Tag>
                            ),
                          },
                          {
                            title: "Total Return",
                            render: (_, r: unknown) => (
                              <>{cell(asRecord(r)?.total_return_rate)}%</>
                            ),
                          },
                          {
                            title: "Sharpe",
                            dataIndex: "sharpe_ratio",
                            render: cell,
                          },
                          {
                            title: "Strategy Score",
                            render: (_, r: unknown) => (
                              <>
                                {cell(asRecord(r)?.strategy_score)} (
                                {cell(asRecord(r)?.grade)})
                              </>
                            ),
                          },
                          {
                            title: "Failure Reason",
                            dataIndex: "failure_reason",
                            render: cell,
                          },
                        ]}
                      />
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        Algorithm Version: {cell(sensitivityReport?.algorithm_version)} ·
                        Input Hash: {String(sensitivityReport?.input_hash ?? "").slice(0, 12)}
                        …
                      </Typography.Text>
                    </>
                  )}
                </Space>
              )}
            </Space>

            <Typography.Title level={5}>Monte Carlo Simulation</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              기존 Backtest의 실제 거래 손익만 확률적으로 재배열/재표본화한
              결과이며 미래 수익을 보장하지 않습니다. Shuffle은 동일 거래를
              순서만 바꾸고, Bootstrap은 복원 추출로 같은 거래가 여러 번
              뽑힐 수 있습니다. 동일 Seed는 항상 동일한 결과를 반환합니다.
              Simulation 횟수는 최소 100회, 최대 10000회까지 지원합니다.
            </Typography.Text>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Space wrap>
                <InputNumber
                  placeholder="Backtest Run ID"
                  value={monteCarloBacktestRunId ?? undefined}
                  onChange={(v) =>
                    setMonteCarloBacktestRunId(typeof v === "number" ? v : null)
                  }
                  min={1}
                  style={{ width: 160 }}
                />
                <Select
                  value={monteCarloMethod}
                  onChange={(v) =>
                    setMonteCarloMethod(
                      v as
                        | "TRADE_ORDER_SHUFFLE"
                        | "BOOTSTRAP_WITH_REPLACEMENT"
                        | "BLOCK_BOOTSTRAP",
                    )
                  }
                  style={{ width: 220 }}
                  options={[
                    { value: "TRADE_ORDER_SHUFFLE", label: "Trade Order Shuffle" },
                    { value: "BOOTSTRAP_WITH_REPLACEMENT", label: "Bootstrap(복원 추출)" },
                    { value: "BLOCK_BOOTSTRAP", label: "Block Bootstrap" },
                  ]}
                />
                <InputNumber
                  placeholder="Simulation Count(100~10000)"
                  value={monteCarloCount ?? undefined}
                  onChange={(v) => setMonteCarloCount(typeof v === "number" ? v : null)}
                  min={100}
                  max={10000}
                  style={{ width: 200 }}
                />
                <InputNumber
                  placeholder="Random Seed"
                  value={monteCarloSeed ?? undefined}
                  onChange={(v) => setMonteCarloSeed(typeof v === "number" ? v : null)}
                  style={{ width: 140 }}
                />
                <Select
                  value={monteCarloConfidenceLevel}
                  onChange={(v) => setMonteCarloConfidenceLevel(v as "0.90" | "0.95" | "0.99")}
                  style={{ width: 140 }}
                  options={[
                    { value: "0.90", label: "90% CI" },
                    { value: "0.95", label: "95% CI" },
                    { value: "0.99", label: "99% CI" },
                  ]}
                />
                <InputNumber
                  placeholder="Ruin Threshold(%)"
                  value={monteCarloRuinThreshold ?? undefined}
                  onChange={(v) =>
                    setMonteCarloRuinThreshold(typeof v === "number" ? v : null)
                  }
                  min={1}
                  max={99}
                  style={{ width: 180 }}
                />
                {monteCarloMethod === "BLOCK_BOOTSTRAP" && (
                  <InputNumber
                    placeholder="Block Size"
                    value={monteCarloBlockSize ?? undefined}
                    onChange={(v) =>
                      setMonteCarloBlockSize(typeof v === "number" ? v : null)
                    }
                    min={1}
                    style={{ width: 140 }}
                  />
                )}
              </Space>
              <Button
                loading={runMonteCarloMutation.isPending}
                disabled={runMonteCarloMutation.isPending || !monteCarloBacktestRunId}
                onClick={() => runMonteCarloMutation.mutate()}
              >
                Monte Carlo Simulation 실행
              </Button>

              {monteCarloReportId != null && (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {monteCarloQuery.isLoading ? (
                    <Typography.Text type="secondary">분석 중…</Typography.Text>
                  ) : (
                    <>
                      <Space wrap>
                        <Tag
                          color={
                            monteCarloReport?.monte_carlo_status === "RESILIENT"
                              ? "success"
                              : monteCarloReport?.monte_carlo_status === "HIGH_RISK"
                                ? "error"
                                : monteCarloReport?.monte_carlo_status === "FRAGILE"
                                  ? "warning"
                                  : monteCarloReport?.monte_carlo_status ===
                                      "INSUFFICIENT_DATA"
                                    ? "default"
                                    : "processing"
                          }
                        >
                          Status: {cell(monteCarloReport?.monte_carlo_status)}
                        </Tag>
                        <Tag>Robustness Score: {cell(monteCarloReport?.robustness_score)}</Tag>
                        <Tag
                          color={
                            Number(monteCarloReport?.risk_of_ruin_percent ?? 0) > 10
                              ? "error"
                              : "default"
                          }
                        >
                          Risk of Ruin: {cell(monteCarloReport?.risk_of_ruin_percent)}%
                        </Tag>
                      </Space>
                      <Descriptions size="small" column={2} bordered title="Confidence Interval / P05·P50·P95">
                        <Descriptions.Item label="Final Equity CI">
                          {cell(monteCarloCI?.final_equity_confidence_low)} ~{" "}
                          {cell(monteCarloCI?.final_equity_confidence_high)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Total Return CI">
                          {cell(monteCarloCI?.total_return_confidence_low)}% ~{" "}
                          {cell(monteCarloCI?.total_return_confidence_high)}%
                        </Descriptions.Item>
                        <Descriptions.Item label="Total Return P05/P50/P95">
                          {cell(monteCarloTotalReturnDist?.P05)}% / {cell(monteCarloTotalReturnDist?.P50)}% /{" "}
                          {cell(monteCarloTotalReturnDist?.P95)}%
                        </Descriptions.Item>
                        <Descriptions.Item label="MDD P50/P95">
                          {cell(monteCarloDrawdownDist?.P50)}% / {cell(monteCarloDrawdownDist?.P95)}%
                        </Descriptions.Item>
                        <Descriptions.Item label="Failed Simulations">
                          {cell(monteCarloReport?.failed_simulation_count)} /{" "}
                          {cell(monteCarloReport?.simulation_count)}
                        </Descriptions.Item>
                      </Descriptions>
                      <Table
                        size="small"
                        dataSource={
                          monteCarloReps
                            ? (["worst", "median", "best"] as const)
                                .map((key) => {
                                  const rep = asRecord(monteCarloReps[key]);
                                  return rep ? { key, ...rep } : null;
                                })
                                .filter((r) => r != null)
                            : []
                        }
                        rowKey={(r) => String(asRecord(r)?.key)}
                        pagination={false}
                        columns={[
                          { title: "구분", dataIndex: "key", render: cell },
                          {
                            title: "Final Equity",
                            dataIndex: "final_equity",
                            render: cell,
                          },
                          {
                            title: "Total Return",
                            render: (_, r: unknown) => (
                              <>{cell(asRecord(r)?.total_return)}%</>
                            ),
                          },
                          {
                            title: "MDD",
                            render: (_, r: unknown) => (
                              <>{cell(asRecord(r)?.maximum_drawdown_percent)}%</>
                            ),
                          },
                          {
                            title: "연속 손실",
                            dataIndex: "consecutive_losses",
                            render: cell,
                          },
                          {
                            title: "Ruin",
                            dataIndex: "ruin",
                            render: (v: boolean) => (
                              <Tag color={v ? "error" : "success"}>{String(v)}</Tag>
                            ),
                          },
                        ]}
                      />
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        Algorithm Version: {cell(monteCarloReport?.algorithm_version)} · Report
                        Input Hash: {String(monteCarloReport?.report_input_hash ?? "").slice(0, 12)}
                        … · Trade PnL Hash:{" "}
                        {String(monteCarloProvenance?.trade_pnl_hash ?? "").slice(0, 12)}…
                      </Typography.Text>
                    </>
                  )}
                </Space>
              )}
            </Space>

            <Typography.Title level={5}>Strategy Explainability</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              이 설명은 자동 승인 또는 투자 권고가 아닙니다. 저장된 검증
              결과를 사람이 검토하기 쉽게 정리한 자료이며, 과거 Backtest
              성과는 미래 수익을 보장하지 않습니다.
            </Typography.Text>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Space wrap>
                <InputNumber
                  placeholder="Backtest Run ID(미지정 시 최신)"
                  value={explainBacktestRunId ?? undefined}
                  onChange={(v) => setExplainBacktestRunId(typeof v === "number" ? v : null)}
                  style={{ width: 220 }}
                />
                <InputNumber
                  placeholder="Quality Gate Report ID"
                  value={explainQualityGateReportId ?? undefined}
                  onChange={(v) => setExplainQualityGateReportId(typeof v === "number" ? v : null)}
                  style={{ width: 200 }}
                />
                <InputNumber
                  placeholder="Sensitivity Report ID"
                  value={explainSensitivityReportId ?? undefined}
                  onChange={(v) => setExplainSensitivityReportId(typeof v === "number" ? v : null)}
                  style={{ width: 200 }}
                />
                <InputNumber
                  placeholder="Monte Carlo Report ID"
                  value={explainMonteCarloReportId ?? undefined}
                  onChange={(v) => setExplainMonteCarloReportId(typeof v === "number" ? v : null)}
                  style={{ width: 200 }}
                />
                <Select
                  value={explainUseLatestWhenMissing}
                  onChange={(v) => setExplainUseLatestWhenMissing(v)}
                  style={{ width: 220 }}
                  options={[
                    { value: true, label: "미지정 항목은 최신 Report 자동 선택" },
                    { value: false, label: "지정한 Report만 사용" },
                  ]}
                />
              </Space>
              <Button
                loading={runExplainabilityMutation.isPending}
                disabled={runExplainabilityMutation.isPending}
                onClick={() => runExplainabilityMutation.mutate()}
              >
                Explainability Report 생성
              </Button>

              {explainabilityReportId != null && (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {explainabilityQuery.isLoading ? (
                    <Typography.Text type="secondary">불러오는 중…</Typography.Text>
                  ) : (
                    <>
                      <Space wrap>
                        <Tag
                          color={
                            explainabilityReport?.completeness_status === "COMPLETE"
                              ? "success"
                              : explainabilityReport?.completeness_status === "SUBSTANTIAL"
                                ? "processing"
                                : explainabilityReport?.completeness_status === "PARTIAL"
                                  ? "warning"
                                  : "error"
                          }
                        >
                          Completeness: {cell(explainabilityReport?.completeness_status)} (
                          {cell(explainabilityReport?.completeness_score)}점)
                        </Tag>
                        <Tag
                          color={
                            explainDecisionSummary?.human_review_required ? "error" : "success"
                          }
                        >
                          Human Review Required:{" "}
                          {String(explainDecisionSummary?.human_review_required ?? false)}
                        </Tag>
                        <Tag color="success">Positive: {cell(explainDecisionSummary?.positive_count)}</Tag>
                        <Tag color="warning">Warning: {cell(explainDecisionSummary?.warning_count)}</Tag>
                        <Tag color="error">Blocking: {cell(explainDecisionSummary?.blocking_count)}</Tag>
                        <Tag>Missing: {cell(explainDecisionSummary?.missing_count)}</Tag>
                      </Space>

                      <Descriptions title="Strategy Overview" bordered size="small" column={3}>
                        <Descriptions.Item label="이름">{cell(explainOverview?.strategy_name)}</Descriptions.Item>
                        <Descriptions.Item label="Market Type">{cell(explainOverview?.market_type)}</Descriptions.Item>
                        <Descriptions.Item label="Owner Type">{cell(explainOverview?.owner_type)}</Descriptions.Item>
                        <Descriptions.Item label="Symbol/Exchange">
                          {cell(explainOverview?.symbol)} / {cell(explainOverview?.exchange)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Timeframe">{cell(explainOverview?.timeframe)}</Descriptions.Item>
                        <Descriptions.Item label="Approval Status">{cell(explainOverview?.approval_status)}</Descriptions.Item>
                        <Descriptions.Item label="Executable Hash" span={3}>
                          <Typography.Text code>{String(explainOverview?.executable_hash ?? "").slice(0, 20)}…</Typography.Text>
                        </Descriptions.Item>
                      </Descriptions>

                      <Typography.Title level={5}>규칙 설명</Typography.Title>
                      <Descriptions bordered size="small" column={1}>
                        <Descriptions.Item label="Entry">
                          {Array.isArray(explainEntry?.sentences) && (explainEntry?.sentences as string[]).length > 0
                            ? (explainEntry?.sentences as string[]).join(" ")
                            : "-"}
                          {explainEntry?.combination_note != null && (
                            <> ({cell(explainEntry?.combination_note)})</>
                          )}
                        </Descriptions.Item>
                        <Descriptions.Item label="Exit">
                          {Array.isArray(explainExit?.sentences)
                            ? (explainExit?.sentences as string[]).join(" ")
                            : "-"}
                        </Descriptions.Item>
                        <Descriptions.Item label="Stop Loss">{cell(explainStopLoss?.sentence)}</Descriptions.Item>
                        <Descriptions.Item label="Take Profit">{cell(explainTakeProfit?.sentence)}</Descriptions.Item>
                        <Descriptions.Item label="Position Sizing">{cell(explainPositionSizing?.sentence)}</Descriptions.Item>
                        <Descriptions.Item label="청산 우선순위">
                          {Array.isArray(explainRules?.exit_priority)
                            ? (explainRules?.exit_priority as string[]).join(" → ")
                            : "-"}
                          {" — "}
                          {cell(explainRules?.exit_priority_note)}
                        </Descriptions.Item>
                      </Descriptions>

                      <Descriptions title="Backtest / Walk-Forward / Quality Gate" bordered size="small" column={2}>
                        <Descriptions.Item label="Backtest Status">{cell(explainBacktest?.status)}</Descriptions.Item>
                        <Descriptions.Item label="Strategy Score/Grade">
                          {cell(explainBacktest?.strategy_score)} / {cell(explainBacktest?.strategy_grade)}
                        </Descriptions.Item>
                        <Descriptions.Item label="Sharpe / MDD">
                          {cell(explainBacktest?.sharpe_ratio)} / {cell(explainBacktest?.maximum_drawdown_rate)}%
                        </Descriptions.Item>
                        <Descriptions.Item label="Trade Count / Win Rate">
                          {cell(explainBacktest?.trade_count)} / {cell(explainBacktest?.win_rate)}%
                        </Descriptions.Item>
                        <Descriptions.Item label="Walk-Forward Overfitting">
                          {cell(explainWalkForward?.overfitting_grade)}(Stability {cell(explainWalkForward?.stability_score)})
                        </Descriptions.Item>
                        <Descriptions.Item label="Quality Gate">
                          {cell(explainQualityGate?.recommendation)} / {cell(explainQualityGate?.risk_grade)}
                        </Descriptions.Item>
                      </Descriptions>

                      <Descriptions title="Sensitivity / Monte Carlo / Portfolio" bordered size="small" column={2}>
                        <Descriptions.Item label="Sensitivity Status">{cell(explainSensitivity?.sensitivity_status)}</Descriptions.Item>
                        <Descriptions.Item label="Stable Range Includes Base">
                          {String(asRecord(explainSensitivity?.stable_range)?.includes_base ?? "-")}
                        </Descriptions.Item>
                        <Descriptions.Item label="Monte Carlo Status">{cell(explainMonteCarlo?.monte_carlo_status)}</Descriptions.Item>
                        <Descriptions.Item label="Risk of Ruin">{cell(explainMonteCarlo?.risk_of_ruin_percent)}%</Descriptions.Item>
                        <Descriptions.Item label="Portfolio Status" span={2}>
                          {explainPortfolio?.status === "NOT_REQUESTED"
                            ? "선택 안 됨"
                            : `${cell(explainPortfolio?.validation_status)} (Duplicate Exposure HIGH ${cell(explainPortfolio?.high_duplicate_exposure_count)}건)`}
                        </Descriptions.Item>
                      </Descriptions>

                      <Typography.Title level={5}>Human Decision Checklist</Typography.Title>
                      <Table
                        size="small"
                        rowKey="code"
                        dataSource={explainChecklist}
                        pagination={false}
                        columns={[
                          { title: "질문", dataIndex: "question" },
                          {
                            title: "답",
                            dataIndex: "answer",
                            render: (v: boolean | null) =>
                              v == null ? (
                                <Tag>근거 없음</Tag>
                              ) : (
                                <Tag color={v ? "error" : "success"}>{String(v)}</Tag>
                              ),
                          },
                          { title: "근거", dataIndex: "basis" },
                        ]}
                      />

                      {explainMissing.length > 0 && (
                        <>
                          <Typography.Title level={5}>Missing Evidence</Typography.Title>
                          <Table
                            size="small"
                            rowKey="category"
                            dataSource={explainMissing}
                            pagination={false}
                            columns={[
                              { title: "카테고리", dataIndex: "category" },
                              { title: "상태", dataIndex: "status" },
                              { title: "설명", dataIndex: "message" },
                            ]}
                          />
                        </>
                      )}

                      <Typography.Title level={5}>Evidence Reference({explainEvidenceRefs.length}건)</Typography.Title>
                      <Table
                        size="small"
                        rowKey="evidence_id"
                        dataSource={explainEvidenceRefs}
                        pagination={{ pageSize: 8 }}
                        columns={[
                          { title: "ID", dataIndex: "evidence_id" },
                          { title: "Type", dataIndex: "evidence_type" },
                          { title: "Field", dataIndex: "source_field" },
                          { title: "Value", dataIndex: "source_value", render: cell },
                          { title: "Status", dataIndex: "source_status" },
                        ]}
                      />

                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        Template Version: {cell(explainabilityReport?.template_version)} · Algorithm
                        Version: {cell(explainabilityReport?.algorithm_version)} · Report Input Hash:{" "}
                        {String(explainabilityReport?.report_input_hash ?? "").slice(0, 12)}…
                      </Typography.Text>
                    </>
                  )}
                </Space>
              )}
            </Space>

            <Typography.Title level={5}>Human Approval Decision</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              이 결정은 실제 Promotion Commit을 실행하지 않습니다.
              APPROVE_FOR_PROMOTION은 다음 단계의 명시적 Commit 입력만
              생성합니다. 과거 Backtest 성과는 미래 수익을 보장하지
              않습니다. 실제 투자 및 주문 실행은 별도 승인 단계입니다.
            </Typography.Text>
            <Space orientation="vertical" size={8} style={{ width: "100%" }}>
              <Button
                loading={createDecisionPackageMutation.isPending}
                disabled={createDecisionPackageMutation.isPending || explainabilityReportId == null}
                onClick={() => createDecisionPackageMutation.mutate()}
              >
                Decision Package 생성(Explainability Report #{explainabilityReportId ?? "-"} 기준)
              </Button>

              {decisionPackageId != null && (
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  {decisionPackageQuery.isLoading ? (
                    <Typography.Text type="secondary">불러오는 중…</Typography.Text>
                  ) : (
                    <>
                      <Space wrap>
                        <Tag
                          color={
                            decisionPackage?.effective_package_status === "READY_FOR_REVIEW"
                              ? "processing"
                              : decisionPackage?.effective_package_status === "DECIDED"
                                ? "success"
                                : decisionPackage?.effective_package_status === "STALE"
                                  ? "error"
                                  : "warning"
                          }
                        >
                          {cell(decisionPackage?.effective_package_status)}
                        </Tag>
                        <Tag color={decisionPackage?.stale ? "error" : "default"}>
                          Stale: {String(decisionPackage?.stale ?? false)}
                        </Tag>
                        <Tag>Blocking: {cell(decisionPackage?.blocking_evidence_count)}</Tag>
                        <Tag>Warning: {cell(decisionPackage?.warning_evidence_count)}</Tag>
                        <Tag>Missing: {cell(decisionPackage?.missing_evidence_count)}</Tag>
                      </Space>
                      {decisionPackage?.stale && (
                        <Alert
                          type="error" showIcon
                          message={`Stale Package — Decision을 생성할 수 없습니다: ${(decisionPackage?.stale_reasons as string[] | undefined)?.join(", ") ?? ""}`}
                        />
                      )}
                      {decisionPackage?.readiness_reason_codes != null &&
                        (decisionPackage.readiness_reason_codes as string[]).length > 0 && (
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            Reason Codes: {(decisionPackage.readiness_reason_codes as string[]).join(", ")}
                          </Typography.Text>
                        )}

                      <Typography.Title level={5}>Decision Checklist</Typography.Title>
                      <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                        {decisionChecklistTemplate.map((item) => {
                          const rec = asRecord(item);
                          const code = String(rec?.checklist_code);
                          return (
                            <Space key={code}>
                              <input
                                type="checkbox"
                                checked={Boolean(checklistConfirmations[code])}
                                onChange={(e) =>
                                  setChecklistConfirmations((prev) => ({
                                    ...prev,
                                    [code]: e.target.checked,
                                  }))
                                }
                              />
                              <Typography.Text>
                                {cell(rec?.question)} {rec?.required ? <Tag color="red">필수</Tag> : <Tag>선택</Tag>}
                              </Typography.Text>
                            </Space>
                          );
                        })}
                      </Space>

                      {!decisionPackage?.has_decision && (
                        <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                          <Space wrap>
                            <Select
                              value={decisionType}
                              onChange={(v) => setDecisionType(v)}
                              style={{ width: 220 }}
                              options={[
                                { value: "APPROVE_FOR_PROMOTION", label: "APPROVE_FOR_PROMOTION" },
                                { value: "REQUEST_CHANGES", label: "REQUEST_CHANGES" },
                                { value: "REJECT", label: "REJECT" },
                              ]}
                            />
                            <Input
                              placeholder="Reason Code"
                              value={reasonCode}
                              onChange={(e) => setReasonCode(e.target.value)}
                              style={{ width: 240 }}
                            />
                            <Space>
                              <input
                                type="checkbox"
                                checked={warningsAcknowledged}
                                onChange={(e) => setWarningsAcknowledged(e.target.checked)}
                              />
                              <Typography.Text>Warning 확인함</Typography.Text>
                            </Space>
                          </Space>
                          <Input.TextArea
                            placeholder="Reason Text(필수)"
                            value={reasonText}
                            onChange={(e) => setReasonText(e.target.value)}
                            rows={2}
                          />
                          <Button
                            type="primary"
                            loading={recordHumanDecisionMutation.isPending}
                            disabled={recordHumanDecisionMutation.isPending || !reasonText.trim()}
                            onClick={() => recordHumanDecisionMutation.mutate()}
                          >
                            Decision 기록
                          </Button>
                        </Space>
                      )}

                      {decisionPackage?.has_decision && humanDecision != null && (
                        <Descriptions title="Human Decision" bordered size="small" column={2}>
                          <Descriptions.Item label="Decision Type">{cell(humanDecision.decision_type)}</Descriptions.Item>
                          <Descriptions.Item label="Reason Code">{cell(humanDecision.reason_code)}</Descriptions.Item>
                          <Descriptions.Item label="Reviewer">{cell(humanDecision.decided_by)}</Descriptions.Item>
                          <Descriptions.Item label="Same Actor Warning">
                            {String(humanDecision.same_actor_warning ?? false)}
                          </Descriptions.Item>
                          <Descriptions.Item label="Promotion Ready">
                            {String(humanDecision.promotion_ready ?? false)}
                          </Descriptions.Item>
                          <Descriptions.Item label="Promotion Readiness Hash">
                            {String(humanDecision.promotion_readiness_hash ?? "-").slice(0, 16)}…
                          </Descriptions.Item>
                        </Descriptions>
                      )}

                      {promotionReadiness != null && (
                        <Alert
                          type={promotionReadiness.ready ? "success" : "info"}
                          showIcon
                          message={`Promotion Readiness: ready=${String(promotionReadiness.ready)}, next_action=${cell(promotionReadiness.next_action)}`}
                        />
                      )}

                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        Package Input Hash: {String(decisionPackage?.package_input_hash ?? "").slice(0, 12)}…
                      </Typography.Text>
                    </>
                  )}
                </Space>
              )}
            </Space>

            <Typography.Title level={5}>Promotion Commit</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Candidate Lifecycle과 Strategy Promotion Status는 서로 다른
              상태입니다. Promotion Commit은 Strategy Promotion Status만
              변경합니다. Activation, Deployment, Runtime 등록은 수행하지
              않습니다. Promotion Commit은 삭제하거나 수정할 수 없는 불변
              기록입니다.
            </Typography.Text>
            {Boolean(decisionPackage?.has_decision) && humanDecision != null && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color={humanDecision.decision_type === "APPROVE_FOR_PROMOTION" ? "success" : "default"}>
                    Decision: {cell(humanDecision.decision_type)}
                  </Tag>
                  <Tag color={promotionStatus?.promotion_committed ? "success" : "processing"}>
                    Promotion Committed: {String(promotionStatus?.promotion_committed ?? false)}
                  </Tag>
                  <Tag color="default">
                    Candidate Lifecycle: {cell(promotionStatus?.candidate_lifecycle_status)}
                  </Tag>
                  <Tag color={promotionStatus?.strategy_promotion_status === "PROMOTION_COMMITTED" ? "success" : "default"}>
                    Strategy Promotion Status: {cell(promotionStatus?.strategy_promotion_status)}
                  </Tag>
                  <Tag color={decisionPackage?.current_effective_status === "STALE" ? "error" : "default"}>
                    Current Effective Status: {cell(decisionPackage?.current_effective_status)}
                  </Tag>
                  <Tag color={promotionReadiness?.stale_after_decision ? "error" : "default"}>
                    Stale After Decision: {String(promotionReadiness?.stale_after_decision ?? false)}
                  </Tag>
                  {Boolean(humanDecision.same_actor_warning) && <Tag color="warning">Same Actor Warning</Tag>}
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  Executable Hash: {String(decisionPackage?.executable_hash ?? "").slice(0, 12)}… · Promotion
                  Readiness Hash: {String(humanDecision.promotion_readiness_hash ?? "").slice(0, 12)}…
                </Typography.Text>

                {promotionStatus?.promotion_committed ? (
                  <>
                    <Descriptions bordered size="small" column={2} title="Promotion 결과">
                      <Descriptions.Item label="Candidate Lifecycle Status">
                        {cell(promotionStatus.candidate_lifecycle_status)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Strategy Promotion Status">
                        {cell(promotionStatus.strategy_promotion_status)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Promotion State Version">
                        {cell(promotionStatus.promotion_state_version)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Promotion Commit ID">
                        {cell(promotionStatus.promotion_commit_id)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Activation Status">{cell(promotionStatus.activation_status)}</Descriptions.Item>
                      <Descriptions.Item label="Deployment Status">{cell(promotionStatus.deployment_status)}</Descriptions.Item>
                      <Descriptions.Item label="Runtime Status">{cell(promotionStatus.runtime_status)}</Descriptions.Item>
                      <Descriptions.Item label="Next Action">{cell(promotionStatus.next_action)}</Descriptions.Item>
                    </Descriptions>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      Candidate Lifecycle과 Strategy Promotion Status는 서로
                      다른 상태입니다 — Candidate Lifecycle은 STEP11 Candidate
                      Promotion Gateway의 상태이며 이번 Commit으로 변경되지
                      않았습니다.
                    </Typography.Text>
                    <Typography.Title level={5}>Promotion History</Typography.Title>
                    <Table
                      size="small"
                      loading={promotionHistoryQuery.isLoading}
                      dataSource={promotionHistoryItems}
                      rowKey={(r) => String(asRecord(r)?.history_id)}
                      pagination={false}
                      columns={[
                        { title: "From", dataIndex: "previous_status", render: cell },
                        { title: "To", dataIndex: "new_status", render: cell },
                        { title: "Actor", dataIndex: "actor", render: cell },
                        { title: "Occurred At", dataIndex: "occurred_at", render: cell },
                        {
                          title: "Event Hash",
                          dataIndex: "event_hash",
                          render: (v: unknown) => cell(String(v ?? "").slice(0, 12) + (v ? "…" : "")),
                        },
                      ]}
                    />
                  </>
                ) : (
                  <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                    <Input
                      placeholder="Commit Reason(필수)"
                      value={commitReason}
                      onChange={(e) => setCommitReason(e.target.value)}
                    />
                    {Boolean(humanDecision.same_actor_warning) && (
                      <Space>
                        <input
                          type="checkbox"
                          checked={acknowledgeSameActorWarning}
                          onChange={(e) => setAcknowledgeSameActorWarning(e.target.checked)}
                        />
                        <Typography.Text>Same Actor Warning 확인함</Typography.Text>
                      </Space>
                    )}
                    <Button
                      type="primary"
                      danger
                      disabled={
                        humanDecision.decision_type !== "APPROVE_FOR_PROMOTION" ||
                        !humanDecision.promotion_ready ||
                        Boolean(promotionReadiness?.stale_after_decision) ||
                        !commitReason.trim() ||
                        (Boolean(humanDecision.same_actor_warning) && !acknowledgeSameActorWarning)
                      }
                      onClick={() => setPromotionCommitModalOpen(true)}
                    >
                      Promotion Commit 실행
                    </Button>
                  </Space>
                )}
              </Space>
            )}

            <Modal
              title="Promotion Commit 확인"
              open={promotionCommitModalOpen}
              onCancel={() => setPromotionCommitModalOpen(false)}
              onOk={() => createPromotionCommitMutation.mutate()}
              okButtonProps={{
                danger: true,
                loading: createPromotionCommitMutation.isPending,
                disabled: confirmationText.trim().toUpperCase() !== "PROMOTE",
              }}
              okText="Promotion Commit 실행"
            >
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Text>
                  Candidate Lifecycle과 Strategy Promotion Status는 서로 다른
                  상태입니다.
                </Typography.Text>
                <Typography.Text>
                  Promotion Commit은 Strategy Promotion Status만 변경합니다
                  (NOT_PROMOTED → PROMOTION_COMMITTED). Candidate Lifecycle은
                  변경되지 않습니다.
                </Typography.Text>
                <Typography.Text>
                  Activation, Deployment, Runtime 등록은 수행하지 않습니다.
                </Typography.Text>
                <Typography.Text>
                  Promotion Commit은 삭제하거나 수정할 수 없는 불변 기록입니다.
                </Typography.Text>
                <Typography.Text strong>계속하려면 PROMOTE를 입력하세요.</Typography.Text>
                <Input
                  placeholder="PROMOTE"
                  value={confirmationText}
                  onChange={(e) => setConfirmationText(e.target.value)}
                />
              </Space>
            </Modal>

            <Typography.Title level={5}>Activation Review & Commit</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Activation은 Runtime을 시작하지 않습니다. Activation은
              Scheduler를 등록하지 않습니다. Activation은 Broker에
              로그인하지 않습니다. Activation은 주문을 전송하지 않습니다.
              LIVE Activation은 실제 자금 위험 검토가 필요합니다. 실제
              자동매매 시작은 별도 Runtime 등록 및 운영 승인 단계입니다.
            </Typography.Text>
            {Boolean(promotionStatus?.promotion_committed) && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color="default">
                    Candidate Lifecycle: {cell(activationStatus?.candidate_lifecycle_status)}
                  </Tag>
                  <Tag color={activationStatus?.strategy_promotion_status === "ACTIVATED" ? "success" : "default"}>
                    Strategy Promotion Status: {cell(activationStatus?.strategy_promotion_status)}
                  </Tag>
                  <Tag color={activationStatus?.activation_committed ? "success" : "processing"}>
                    Activation Committed: {String(activationStatus?.activation_committed ?? false)}
                  </Tag>
                </Space>

                {!activationStatus?.activation_committed && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      1. Activation Target 설정
                    </Typography.Title>
                    <Space wrap>
                      <Select
                        style={{ width: 160 }}
                        value={activationTargetAccountKind}
                        onChange={(v) => setActivationTargetAccountKind(v)}
                        options={[
                          { value: "PAPER", label: "PAPER Account" },
                          { value: "USER_BROKER", label: "USER_BROKER Account" },
                        ]}
                      />
                      <Select
                        style={{ width: 160 }}
                        value={activationExecutionMode}
                        onChange={(v) => setActivationExecutionMode(v)}
                        options={[
                          { value: "PAPER", label: "PAPER" },
                          { value: "LIVE", label: "LIVE" },
                        ]}
                      />
                      <Input
                        placeholder="Market Type(예: STOCK, CRYPTO)"
                        style={{ width: 180 }}
                        value={activationTargetMarketType}
                        onChange={(e) => setActivationTargetMarketType(e.target.value)}
                      />
                      <Input
                        placeholder="Broker Code(PAPER/KIWOOM/UPBIT)"
                        style={{ width: 200 }}
                        value={activationTargetBrokerCode}
                        onChange={(e) => setActivationTargetBrokerCode(e.target.value)}
                      />
                      <InputNumber
                        placeholder="Account ID"
                        style={{ width: 140 }}
                        value={activationTargetAccountId ?? undefined}
                        onChange={(v) => setActivationTargetAccountId(typeof v === "number" ? v : null)}
                      />
                    </Space>
                    <Input
                      placeholder="Review Note(선택)"
                      value={activationReviewNote}
                      onChange={(e) => setActivationReviewNote(e.target.value)}
                    />
                    <Button
                      onClick={() => createActivationReviewPackageMutation.mutate()}
                      loading={createActivationReviewPackageMutation.isPending}
                      disabled={
                        !promotionStatus?.promotion_commit_id ||
                        !activationTargetMarketType.trim() ||
                        !activationTargetBrokerCode.trim() ||
                        activationTargetAccountId == null
                      }
                    >
                      Activation Review Package 생성
                    </Button>
                  </>
                )}

                {activationPackage != null && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      2. Readiness
                    </Typography.Title>
                    <Space wrap>
                      <Tag color={activationPackage.readiness_status === "READY_FOR_ACTIVATION_REVIEW" ? "success" : "error"}>
                        {cell(activationPackage.readiness_status)}
                      </Tag>
                      <Tag color="default">Execution Mode: {cell(activationPackage.requested_execution_mode)}</Tag>
                    </Space>
                    {extractRows(activationPackage.blocking_reason_codes).length > 0 && (
                      <Alert
                        type="error"
                        showIcon
                        message="Blocking"
                        description={extractRows(activationPackage.blocking_reason_codes).join(", ")}
                      />
                    )}
                    {extractRows(activationPackage.warning_reason_codes).length > 0 && (
                      <Alert
                        type="warning"
                        showIcon
                        message="Warning"
                        description={extractRows(activationPackage.warning_reason_codes).join(", ")}
                      />
                    )}

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      3. Checklist
                    </Typography.Title>
                    <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                      {activationChecklistTemplate.map((row) => {
                        const item = asRecord(row);
                        const code = String(item?.checklist_code ?? "");
                        return (
                          <Space key={code}>
                            <input
                              type="checkbox"
                              checked={Boolean(activationChecklistConfirmations[code])}
                              onChange={(e) =>
                                setActivationChecklistConfirmations((prev) => ({
                                  ...prev,
                                  [code]: e.target.checked,
                                }))
                              }
                            />
                            <Typography.Text>
                              {cell(item?.question)} {item?.required ? "(필수)" : "(선택)"}
                            </Typography.Text>
                          </Space>
                        );
                      })}
                    </Space>

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      4. Human Activation Decision
                    </Typography.Title>
                    {activationDecision == null ? (
                      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                        <Select
                          style={{ width: 260 }}
                          value={activationDecisionType}
                          onChange={(v) => setActivationDecisionType(v)}
                          options={[
                            { value: "APPROVE_ACTIVATION", label: "APPROVE_ACTIVATION" },
                            { value: "REQUEST_ACTIVATION_CHANGES", label: "REQUEST_ACTIVATION_CHANGES" },
                            { value: "REJECT_ACTIVATION", label: "REJECT_ACTIVATION" },
                          ]}
                        />
                        <Input
                          placeholder="Reason Code"
                          value={activationReasonCode}
                          onChange={(e) => setActivationReasonCode(e.target.value)}
                        />
                        <Input
                          placeholder="Reason Text"
                          value={activationReasonText}
                          onChange={(e) => setActivationReasonText(e.target.value)}
                        />
                        <Space>
                          <input
                            type="checkbox"
                            checked={activationWarningsAcknowledged}
                            onChange={(e) => setActivationWarningsAcknowledged(e.target.checked)}
                          />
                          <Typography.Text>모든 Warning 확인함</Typography.Text>
                        </Space>
                        <Button
                          onClick={() => recordActivationDecisionMutation.mutate()}
                          loading={recordActivationDecisionMutation.isPending}
                          disabled={!activationReasonCode.trim() || !activationReasonText.trim()}
                        >
                          Decision 기록
                        </Button>
                      </Space>
                    ) : (
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label="Decision Type">{cell(activationDecision.decision_type)}</Descriptions.Item>
                        <Descriptions.Item label="Activation Ready">
                          {String(activationDecision.activation_ready ?? false)}
                        </Descriptions.Item>
                      </Descriptions>
                    )}

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      5. Activation Commit
                    </Typography.Title>
                    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                      <Input
                        placeholder="Commit Reason(필수)"
                        value={activationCommitReason}
                        onChange={(e) => setActivationCommitReason(e.target.value)}
                      />
                      {Boolean(activationDecision?.same_actor_warning) && (
                        <Space>
                          <input
                            type="checkbox"
                            checked={activationAcknowledgeSameActorWarning}
                            onChange={(e) => setActivationAcknowledgeSameActorWarning(e.target.checked)}
                          />
                          <Typography.Text>Same Actor Warning 확인함</Typography.Text>
                        </Space>
                      )}
                      <Button
                        type="primary"
                        danger
                        disabled={
                          activationDecision?.decision_type !== "APPROVE_ACTIVATION" ||
                          !activationDecision?.activation_ready ||
                          !activationCommitReason.trim() ||
                          (Boolean(activationDecision?.same_actor_warning) && !activationAcknowledgeSameActorWarning)
                        }
                        onClick={() => setActivationCommitModalOpen(true)}
                      >
                        Activation Commit 실행
                      </Button>
                    </Space>
                  </>
                )}

                {Boolean(activationStatus?.activation_committed) && (
                  <Descriptions bordered size="small" column={2} title="Activation 결과">
                    <Descriptions.Item label="Candidate Lifecycle Status">
                      {cell(activationStatus?.candidate_lifecycle_status)}
                    </Descriptions.Item>
                    <Descriptions.Item label="Strategy Promotion Status">
                      {cell(activationStatus?.strategy_promotion_status)}
                    </Descriptions.Item>
                    <Descriptions.Item label="Deployment Status">{cell(activationStatus?.deployment_status)}</Descriptions.Item>
                    <Descriptions.Item label="Runtime Status">{cell(activationStatus?.runtime_status)}</Descriptions.Item>
                    <Descriptions.Item label="Scheduler Status">{cell(activationStatus?.scheduler_status)}</Descriptions.Item>
                    <Descriptions.Item label="Broker Connection Status">
                      {cell(activationStatus?.broker_connection_status)}
                    </Descriptions.Item>
                    <Descriptions.Item label="Order Execution Status">
                      {cell(activationStatus?.order_execution_status)}
                    </Descriptions.Item>
                    <Descriptions.Item label="Next Action">{cell(activationStatus?.next_action)}</Descriptions.Item>
                  </Descriptions>
                )}
              </Space>
            )}

            <Modal
              title="Activation Commit 확인"
              open={activationCommitModalOpen}
              onCancel={() => setActivationCommitModalOpen(false)}
              onOk={() => createActivationCommitMutation.mutate()}
              okButtonProps={{
                danger: true,
                loading: createActivationCommitMutation.isPending,
                disabled: activationConfirmationText.trim().toUpperCase() !== "ACTIVATE",
              }}
              okText="Activation Commit 실행"
            >
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Text>
                  이 작업은 Strategy Promotion Status를 ACTIVATED로
                  전환합니다.
                </Typography.Text>
                <Typography.Text>
                  Runtime, Scheduler, Broker 연결 또는 주문 실행은 수행하지
                  않습니다.
                </Typography.Text>
                <Typography.Text>
                  Activation Commit은 수정하거나 삭제할 수 없는 불변
                  기록입니다.
                </Typography.Text>
                <Typography.Text strong>계속하려면 ACTIVATE를 입력하세요.</Typography.Text>
                <Input
                  placeholder="ACTIVATE"
                  value={activationConfirmationText}
                  onChange={(e) => setActivationConfirmationText(e.target.value)}
                />
              </Space>
            </Modal>

            <Typography.Title level={5}>Runtime Registration</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Runtime Registration은 Runtime을 시작하지 않습니다. Scheduler는
              등록되거나 시작되지 않습니다. Broker 연결이나 로그인을
              수행하지 않습니다. 실시간 데이터 구독을 수행하지 않습니다.
              주문을 생성하거나 전송하지 않습니다. 실제 자동매매 시작은
              별도 운영 단계입니다.
            </Typography.Text>
            {Boolean(activationStatus?.activation_committed) && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color="default">Candidate Lifecycle: {cell(activationStatus?.candidate_lifecycle_status)}</Tag>
                  <Tag color={runtimeRegStatus?.strategy_promotion_status === "ACTIVATED" ? "success" : "default"}>
                    Promotion Status: {cell(runtimeRegStatus?.strategy_promotion_status)}
                  </Tag>
                  <Tag color={runtimeRegStatus?.registered ? "success" : "processing"}>
                    Registered: {String(runtimeRegStatus?.registered ?? false)}
                  </Tag>
                  <Tag color="default">Total Registrations: {String(runtimeRegStatus?.total_registrations ?? 0)}</Tag>
                </Space>

                {runtimeRegScopeItems.length > 0 && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      Runtime Scopes(동일 Strategy의 여러 등록)
                    </Typography.Title>
                    <Table
                      size="small"
                      loading={runtimeRegScopesQuery.isLoading}
                      dataSource={runtimeRegScopeItems}
                      rowKey={(r) => String(asRecord(r)?.runtime_scope_hash)}
                      pagination={false}
                      columns={[
                        { title: "User", dataIndex: "target_user_id", render: cell },
                        {
                          title: "Account",
                          render: (_: unknown, r: unknown) => {
                            const rec = asRecord(r);
                            return cell(rec?.target_user_broker_account_id ?? rec?.target_paper_account_id);
                          },
                        },
                        { title: "Market", dataIndex: "market_type", render: cell },
                        { title: "Broker", dataIndex: "broker_code", render: cell },
                        { title: "Execution Mode", dataIndex: "execution_mode", render: cell },
                        { title: "Strategy Version", dataIndex: "strategy_version", render: cell },
                        { title: "Registration Status", dataIndex: "registration_status", render: cell },
                        {
                          title: "Enabled/Running",
                          render: (_: unknown, r: unknown) => {
                            const rec = asRecord(r);
                            return `${String(rec?.registry_enabled ?? false)} / ${String(rec?.registry_running ?? false)}`;
                          },
                        },
                      ]}
                    />
                  </>
                )}

                {!runtimeRegStatus?.registered && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      1~3. Runtime Target 및 Scope 설정
                    </Typography.Title>
                    <Space wrap>
                      <Select
                        style={{ width: 160 }}
                        value={runtimeRegAccountKind}
                        onChange={(v) => setRuntimeRegAccountKind(v)}
                        options={[
                          { value: "PAPER", label: "PAPER Account" },
                          { value: "USER_BROKER", label: "USER_BROKER Account" },
                        ]}
                      />
                      <Select
                        style={{ width: 160 }}
                        value={runtimeRegExecutionMode}
                        onChange={(v) => setRuntimeRegExecutionMode(v)}
                        options={[
                          { value: "PAPER", label: "PAPER" },
                          { value: "LIVE", label: "LIVE" },
                        ]}
                      />
                      <Input
                        placeholder="Market Type"
                        style={{ width: 160 }}
                        value={runtimeRegMarketType}
                        onChange={(e) => setRuntimeRegMarketType(e.target.value)}
                      />
                      <Input
                        placeholder="Broker Code"
                        style={{ width: 180 }}
                        value={runtimeRegBrokerCode}
                        onChange={(e) => setRuntimeRegBrokerCode(e.target.value)}
                      />
                      <InputNumber
                        placeholder="Account ID"
                        style={{ width: 140 }}
                        value={runtimeRegAccountId ?? undefined}
                        onChange={(v) => setRuntimeRegAccountId(typeof v === "number" ? v : null)}
                      />
                    </Space>
                    <Button
                      onClick={() => createRuntimeRegistrationPackageMutation.mutate()}
                      loading={createRuntimeRegistrationPackageMutation.isPending}
                      disabled={
                        !activationStatus?.activation_commit_id ||
                        !runtimeRegMarketType.trim() ||
                        !runtimeRegBrokerCode.trim() ||
                        runtimeRegAccountId == null
                      }
                    >
                      Runtime Registration Package 생성
                    </Button>
                  </>
                )}

                {runtimeRegPackage != null && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      4. Readiness / Risk / Account / Credential
                    </Typography.Title>
                    <Space wrap>
                      <Tag color={runtimeRegPackage.registration_readiness_status === "READY_FOR_RUNTIME_REGISTRATION" ? "success" : "error"}>
                        {cell(runtimeRegPackage.registration_readiness_status)}
                      </Tag>
                      <Tag color="default">Execution Mode: {cell(runtimeRegPackage.execution_mode)}</Tag>
                      <Tag color="default">Strategy Version: {cell(runtimeRegPackage.strategy_version)}</Tag>
                    </Space>
                    {extractRows(runtimeRegPackage.blocking_reason_codes).length > 0 && (
                      <Alert
                        type="error"
                        showIcon
                        message="Blocking"
                        description={extractRows(runtimeRegPackage.blocking_reason_codes).join(", ")}
                      />
                    )}
                    {extractRows(runtimeRegPackage.warning_reason_codes).length > 0 && (
                      <Alert
                        type="warning"
                        showIcon
                        message="Warning"
                        description={extractRows(runtimeRegPackage.warning_reason_codes).join(", ")}
                      />
                    )}

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      5. Checklist
                    </Typography.Title>
                    <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                      {runtimeRegChecklistTemplate.map((row) => {
                        const item = asRecord(row);
                        const code = String(item?.checklist_code ?? "");
                        return (
                          <Space key={code}>
                            <input
                              type="checkbox"
                              checked={Boolean(runtimeRegChecklistConfirmations[code])}
                              onChange={(e) =>
                                setRuntimeRegChecklistConfirmations((prev) => ({
                                  ...prev,
                                  [code]: e.target.checked,
                                }))
                              }
                            />
                            <Typography.Text>
                              {cell(item?.question)} {item?.required ? "(필수)" : "(선택)"}
                            </Typography.Text>
                          </Space>
                        );
                      })}
                    </Space>

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      6. Human Decision
                    </Typography.Title>
                    {runtimeRegDecision == null ? (
                      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                        <Select
                          style={{ width: 300 }}
                          value={runtimeRegDecisionType}
                          onChange={(v) => setRuntimeRegDecisionType(v)}
                          options={[
                            { value: "APPROVE_RUNTIME_REGISTRATION", label: "APPROVE_RUNTIME_REGISTRATION" },
                            { value: "REQUEST_RUNTIME_REGISTRATION_CHANGES", label: "REQUEST_RUNTIME_REGISTRATION_CHANGES" },
                            { value: "REJECT_RUNTIME_REGISTRATION", label: "REJECT_RUNTIME_REGISTRATION" },
                          ]}
                        />
                        <Input
                          placeholder="Reason Code"
                          value={runtimeRegReasonCode}
                          onChange={(e) => setRuntimeRegReasonCode(e.target.value)}
                        />
                        <Input
                          placeholder="Reason Text"
                          value={runtimeRegReasonText}
                          onChange={(e) => setRuntimeRegReasonText(e.target.value)}
                        />
                        <Space>
                          <input
                            type="checkbox"
                            checked={runtimeRegWarningsAcknowledged}
                            onChange={(e) => setRuntimeRegWarningsAcknowledged(e.target.checked)}
                          />
                          <Typography.Text>모든 Warning 확인함</Typography.Text>
                        </Space>
                        <Button
                          onClick={() => recordRuntimeRegistrationDecisionMutation.mutate()}
                          loading={recordRuntimeRegistrationDecisionMutation.isPending}
                          disabled={!runtimeRegReasonCode.trim() || !runtimeRegReasonText.trim()}
                        >
                          Decision 기록
                        </Button>
                      </Space>
                    ) : (
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label="Decision Type">{cell(runtimeRegDecision.decision_type)}</Descriptions.Item>
                        <Descriptions.Item label="Registration Ready">
                          {String(runtimeRegDecision.registration_ready ?? false)}
                        </Descriptions.Item>
                      </Descriptions>
                    )}

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      7. Runtime Registration Commit
                    </Typography.Title>
                    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                      <Input
                        placeholder="Commit Reason(필수)"
                        value={runtimeRegCommitReason}
                        onChange={(e) => setRuntimeRegCommitReason(e.target.value)}
                      />
                      {Boolean(runtimeRegDecision?.same_actor_warning) && (
                        <Space>
                          <input
                            type="checkbox"
                            checked={runtimeRegAcknowledgeSameActorWarning}
                            onChange={(e) => setRuntimeRegAcknowledgeSameActorWarning(e.target.checked)}
                          />
                          <Typography.Text>Same Actor Warning 확인함</Typography.Text>
                        </Space>
                      )}
                      <Button
                        type="primary"
                        danger
                        disabled={
                          runtimeRegDecision?.decision_type !== "APPROVE_RUNTIME_REGISTRATION" ||
                          !runtimeRegDecision?.registration_ready ||
                          !runtimeRegCommitReason.trim() ||
                          (Boolean(runtimeRegDecision?.same_actor_warning) && !runtimeRegAcknowledgeSameActorWarning)
                        }
                        onClick={() => setRuntimeRegCommitModalOpen(true)}
                      >
                        Runtime Registration Commit 실행
                      </Button>
                    </Space>
                  </>
                )}

                {Boolean(runtimeRegStatus?.registered) && (
                  <>
                    <Descriptions bordered size="small" column={2} title="Runtime Registration 결과">
                      <Descriptions.Item label="Registration Status">
                        {cell(runtimeRegStatus?.registration_status)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Runtime Status">{cell(runtimeRegStatus?.runtime_status)}</Descriptions.Item>
                      <Descriptions.Item label="Scheduler Status">{cell(runtimeRegStatus?.scheduler_status)}</Descriptions.Item>
                      <Descriptions.Item label="Broker Connection Status">
                        {cell(runtimeRegStatus?.broker_connection_status)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Market Data Status">{cell(runtimeRegStatus?.market_data_status)}</Descriptions.Item>
                      <Descriptions.Item label="Signal Status">{cell(runtimeRegStatus?.signal_status)}</Descriptions.Item>
                      <Descriptions.Item label="Order Execution Status">
                        {cell(runtimeRegStatus?.order_execution_status)}
                      </Descriptions.Item>
                      <Descriptions.Item label="Registry Enabled/Running">
                        {String(runtimeRegStatus?.registry_enabled ?? false)} / {String(runtimeRegStatus?.registry_running ?? false)}
                      </Descriptions.Item>
                    </Descriptions>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      Runtime Registration History
                    </Typography.Title>
                    <Table
                      size="small"
                      loading={runtimeRegHistoryQuery.isLoading}
                      dataSource={runtimeRegHistoryItems}
                      rowKey={(r) => String(asRecord(r)?.event) + String(asRecord(r)?.occurred_at)}
                      pagination={false}
                      columns={[
                        { title: "Event", dataIndex: "event", render: cell },
                        { title: "Actor", dataIndex: "actor", render: cell },
                        { title: "Occurred At", dataIndex: "occurred_at", render: cell },
                      ]}
                    />
                  </>
                )}
              </Space>
            )}

            <Modal
              title="Runtime Registration Commit 확인"
              open={runtimeRegCommitModalOpen}
              onCancel={() => setRuntimeRegCommitModalOpen(false)}
              onOk={() => createRuntimeRegistrationCommitMutation.mutate()}
              okButtonProps={{
                danger: true,
                loading: createRuntimeRegistrationCommitMutation.isPending,
                disabled: runtimeRegConfirmationText.trim().toUpperCase() !== "REGISTER",
              }}
              okText="Runtime Registration Commit 실행"
            >
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Text>
                  이 작업은 Runtime Registry에 비실행 상태로 등록합니다.
                </Typography.Text>
                <Typography.Text>
                  Runtime, Scheduler, Broker 연결, 실시간 시세 구독 또는
                  주문 생성/전송은 수행하지 않습니다.
                </Typography.Text>
                <Typography.Text>
                  Runtime Registration Commit은 수정하거나 삭제할 수 없는
                  불변 기록입니다.
                </Typography.Text>
                <Typography.Text strong>계속하려면 REGISTER를 입력하세요.</Typography.Text>
                <Input
                  placeholder="REGISTER"
                  value={runtimeRegConfirmationText}
                  onChange={(e) => setRuntimeRegConfirmationText(e.target.value)}
                />
              </Space>
            </Modal>

            <Typography.Title level={5}>Deployment Readiness</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Deployment Readiness Commit은 Runtime을 시작하지 않습니다.
              Scheduler Plan은 실제 Job으로 등록되지 않습니다. Broker
              연결이나 로그인을 수행하지 않습니다. 실시간 시세 구독을
              수행하지 않습니다. 주문을 생성하거나 전송하지 않습니다.
              실제 자동매매 시작은 별도 STEP13 승인 단계입니다.
            </Typography.Text>
            {runtimeRegScopeItems.length > 0 && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color={deployStatus?.deployed ? "success" : "processing"}>
                    Deployed: {String(deployStatus?.deployed ?? false)}
                  </Tag>
                  <Tag color="default">Total Deployments: {String(deployStatus?.total_deployments ?? 0)}</Tag>
                </Space>

                <Typography.Title level={5} style={{ marginTop: 8 }}>
                  Runtime Scope별 Deployment Readiness
                </Typography.Title>
                <Table
                  size="small"
                  loading={runtimeRegScopesQuery.isLoading || deployScopesQuery.isLoading}
                  dataSource={runtimeRegScopeItems}
                  rowKey={(r) => String(asRecord(r)?.runtime_scope_hash)}
                  pagination={false}
                  columns={[
                    { title: "User", dataIndex: "target_user_id", render: cell },
                    {
                      title: "Account",
                      render: (_: unknown, r: unknown) => {
                        const rec = asRecord(r);
                        return cell(rec?.target_user_broker_account_id ?? rec?.target_paper_account_id);
                      },
                    },
                    { title: "Market", dataIndex: "market_type", render: cell },
                    { title: "Broker", dataIndex: "broker_code", render: cell },
                    { title: "Execution Mode", dataIndex: "execution_mode", render: cell },
                    { title: "Strategy Version", dataIndex: "strategy_version", render: cell },
                    {
                      title: "Runtime Registration",
                      dataIndex: "registration_status",
                      render: cell,
                    },
                    {
                      title: "Runtime Enabled/Running",
                      render: (_: unknown, r: unknown) => {
                        const rec = asRecord(r);
                        return `${String(rec?.registry_enabled ?? false)} / ${String(rec?.registry_running ?? false)}`;
                      },
                    },
                    {
                      title: "Deployment Status",
                      render: (_: unknown, r: unknown) => {
                        const rec = asRecord(r);
                        const scopeHash = String(rec?.runtime_scope_hash);
                        const isDeployed = deployedScopeHashes.has(scopeHash);
                        return (
                          <Tag color={isDeployed ? "success" : "default"}>
                            {isDeployed ? "READY_TO_START" : "NOT_DEPLOYED"}
                          </Tag>
                        );
                      },
                    },
                    {
                      title: "Scheduler Plan",
                      render: (_: unknown, r: unknown) => {
                        const rec = asRecord(r);
                        const scopeHash = String(rec?.runtime_scope_hash);
                        const scopeRow = deployScopeItems.find(
                          (s) => String(asRecord(s)?.runtime_scope_hash) === scopeHash,
                        );
                        if (scopeRow == null) return cell(undefined);
                        return `enabled=${String(asRecord(scopeRow)?.scheduler_plan_enabled ?? false)}`;
                      },
                    },
                    {
                      title: "Action",
                      render: (_: unknown, r: unknown) => {
                        const rec = asRecord(r);
                        const scopeHash = String(rec?.runtime_scope_hash);
                        const isDeployed = deployedScopeHashes.has(scopeHash);
                        if (isDeployed) return <Typography.Text type="secondary">완료</Typography.Text>;
                        return (
                          <Button
                            size="small"
                            onClick={() => {
                              setDeploySelectedScopeHash(scopeHash);
                              setDeploySelectedCommitId(Number(rec?.runtime_registration_commit_id));
                              setDeploySelectedRegistryId(
                                rec?.runtime_registry_id != null ? Number(rec.runtime_registry_id) : null,
                              );
                              setDeployPackageId(null);
                            }}
                          >
                            Deployment Readiness 시작
                          </Button>
                        );
                      },
                    },
                  ]}
                />

                {deploySelectedScopeHash != null && deployPackageId == null && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      1. Deployment Readiness Package 생성
                    </Typography.Title>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      선택된 Runtime Scope: {deploySelectedScopeHash}
                    </Typography.Text>
                    <br />
                    <Button
                      onClick={() => createDeploymentReadinessPackageMutation.mutate()}
                      loading={createDeploymentReadinessPackageMutation.isPending}
                      disabled={deploySelectedCommitId == null || deploySelectedRegistryId == null}
                    >
                      Deployment Readiness Package 생성
                    </Button>
                  </>
                )}

                {deployPackage != null && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      2. Readiness / Risk / Account / Credential / Scheduler Plan
                    </Typography.Title>
                    <Space wrap>
                      <Tag color={deployPackage.readiness_status === "READY_FOR_DEPLOYMENT" ? "success" : "error"}>
                        {cell(deployPackage.readiness_status)}
                      </Tag>
                      <Tag color="default">Execution Mode: {cell(deployPackage.execution_mode)}</Tag>
                      <Tag color="default">Strategy Version: {cell(deployPackage.strategy_version)}</Tag>
                    </Space>
                    {extractRows(deployPackage.blocking_reason_codes).length > 0 && (
                      <Alert
                        type="error"
                        showIcon
                        message="Blocking"
                        description={extractRows(deployPackage.blocking_reason_codes).join(", ")}
                      />
                    )}
                    {extractRows(deployPackage.warning_reason_codes).length > 0 && (
                      <Alert
                        type="warning"
                        showIcon
                        message="Warning"
                        description={extractRows(deployPackage.warning_reason_codes).join(", ")}
                      />
                    )}
                    <Alert
                      type="info"
                      showIcon
                      message="Scheduler Plan은 비활성 상태로만 저장됩니다"
                      description="enabled=false, registered_to_scheduler=false, scheduler_job_id=NULL — 실제 Scheduler Job은 생성되지 않습니다."
                    />

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      3. Checklist
                    </Typography.Title>
                    <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                      {deployChecklistTemplate.map((row) => {
                        const item = asRecord(row);
                        const code = String(item?.checklist_code ?? "");
                        return (
                          <Space key={code}>
                            <input
                              type="checkbox"
                              checked={Boolean(deployChecklistConfirmations[code])}
                              onChange={(e) =>
                                setDeployChecklistConfirmations((prev) => ({
                                  ...prev,
                                  [code]: e.target.checked,
                                }))
                              }
                            />
                            <Typography.Text>
                              {cell(item?.question)} {item?.required ? "(필수)" : "(선택)"}
                            </Typography.Text>
                          </Space>
                        );
                      })}
                    </Space>

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      4. Human Decision
                    </Typography.Title>
                    {deployDecision == null ? (
                      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                        <Select
                          style={{ width: 300 }}
                          value={deployDecisionType}
                          onChange={(v) => setDeployDecisionType(v)}
                          options={[
                            { value: "APPROVE_DEPLOYMENT", label: "APPROVE_DEPLOYMENT" },
                            { value: "REQUEST_DEPLOYMENT_CHANGES", label: "REQUEST_DEPLOYMENT_CHANGES" },
                            { value: "REJECT_DEPLOYMENT", label: "REJECT_DEPLOYMENT" },
                          ]}
                        />
                        <Input
                          placeholder="Reason Code"
                          value={deployReasonCode}
                          onChange={(e) => setDeployReasonCode(e.target.value)}
                        />
                        <Input
                          placeholder="Reason Text"
                          value={deployReasonText}
                          onChange={(e) => setDeployReasonText(e.target.value)}
                        />
                        <Space>
                          <input
                            type="checkbox"
                            checked={deployWarningsAcknowledged}
                            onChange={(e) => setDeployWarningsAcknowledged(e.target.checked)}
                          />
                          <Typography.Text>모든 Warning 확인함</Typography.Text>
                        </Space>
                        <Button
                          onClick={() => recordDeploymentReadinessDecisionMutation.mutate()}
                          loading={recordDeploymentReadinessDecisionMutation.isPending}
                          disabled={!deployReasonCode.trim() || !deployReasonText.trim()}
                        >
                          Decision 기록
                        </Button>
                      </Space>
                    ) : (
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label="Decision Type">{cell(deployDecision.decision_type)}</Descriptions.Item>
                        <Descriptions.Item label="Deployment Ready">
                          {String(deployDecision.deployment_ready ?? false)}
                        </Descriptions.Item>
                      </Descriptions>
                    )}

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      5. Deployment Readiness Commit
                    </Typography.Title>
                    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                      <Input
                        placeholder="Commit Reason(필수)"
                        value={deployCommitReason}
                        onChange={(e) => setDeployCommitReason(e.target.value)}
                      />
                      {Boolean(deployDecision?.same_actor_warning) && (
                        <Space>
                          <input
                            type="checkbox"
                            checked={deployAcknowledgeSameActorWarning}
                            onChange={(e) => setDeployAcknowledgeSameActorWarning(e.target.checked)}
                          />
                          <Typography.Text>Same Actor Warning 확인함</Typography.Text>
                        </Space>
                      )}
                      <Button
                        type="primary"
                        danger
                        disabled={
                          deployDecision?.decision_type !== "APPROVE_DEPLOYMENT" ||
                          !deployDecision?.deployment_ready ||
                          !deployCommitReason.trim() ||
                          (Boolean(deployDecision?.same_actor_warning) && !deployAcknowledgeSameActorWarning)
                        }
                        onClick={() => setDeployCommitModalOpen(true)}
                      >
                        Deployment Readiness Commit 실행
                      </Button>
                    </Space>
                  </>
                )}

                {deployHistoryItems.length > 0 && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      Deployment Readiness History
                    </Typography.Title>
                    <Table
                      size="small"
                      loading={deployHistoryQuery.isLoading}
                      dataSource={deployHistoryItems}
                      rowKey={(r) => String(asRecord(r)?.history_id)}
                      pagination={false}
                      columns={[
                        { title: "Event", dataIndex: "event_type", render: cell },
                        { title: "Actor", dataIndex: "actor_id", render: cell },
                        { title: "Occurred At", dataIndex: "occurred_at", render: cell },
                      ]}
                    />
                  </>
                )}
              </Space>
            )}

            <Modal
              title="Deployment Readiness Commit 확인"
              open={deployCommitModalOpen}
              onCancel={() => setDeployCommitModalOpen(false)}
              onOk={() => createDeploymentReadinessCommitMutation.mutate()}
              okButtonProps={{
                danger: true,
                loading: createDeploymentReadinessCommitMutation.isPending,
                disabled: deployConfirmationText.trim().toUpperCase() !== "DEPLOY",
              }}
              okText="Deployment Readiness Commit 실행"
            >
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Text>
                  이 작업은 StrategyDeployment를 READY_TO_START 상태로만
                  확정합니다. Runtime을 시작하지 않습니다.
                </Typography.Text>
                <Typography.Text>
                  Scheduler Plan은 비활성(enabled=false)으로만 저장되며 실제
                  Job으로 등록되지 않습니다.
                </Typography.Text>
                <Typography.Text>
                  Broker 연결/로그인, 실시간 시세 구독, 주문 생성/전송은
                  수행하지 않습니다.
                </Typography.Text>
                <Typography.Text>
                  실제 자동매매 시작은 이 Commit과 별도인 STEP13 운영 승인
                  단계에서 이뤄집니다.
                </Typography.Text>
                <Typography.Text>
                  Deployment Readiness Commit은 수정하거나 삭제할 수 없는
                  불변 기록입니다.
                </Typography.Text>
                <Typography.Text strong>계속하려면 DEPLOY를 입력하세요.</Typography.Text>
                <Input
                  placeholder="DEPLOY"
                  value={deployConfirmationText}
                  onChange={(e) => setDeployConfirmationText(e.target.value)}
                />
              </Space>
            </Modal>

            <Typography.Title level={5}>Operation Readiness Certification(STEP12 마지막 단계)</Typography.Title>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Operation Readiness Commit은 Runtime을 시작하지 않습니다.
              Scheduler는 실제로 등록되지 않습니다. Broker 연결이나 로그인을
              수행하지 않습니다. 실시간 시세 구독을 수행하지 않습니다. 주문을
              생성하거나 전송하지 않습니다. 실제 자동매매 시작(START)은 이
              STEP과 별도인 STEP13 운영 승인 단계입니다.
            </Typography.Text>
            {deployScopeItems.length > 0 && (
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Space wrap>
                  <Tag color={opStatus?.certified ? "success" : "processing"}>
                    Certified: {String(opStatus?.certified ?? false)}
                  </Tag>
                  <Tag color="default">Total Certifications: {String(opStatus?.total_certifications ?? 0)}</Tag>
                </Space>

                <Typography.Title level={5} style={{ marginTop: 8 }}>
                  Deployment Scope별 Operation Readiness
                </Typography.Title>
                <Table
                  size="small"
                  loading={deployScopesQuery.isLoading || opCommitsQuery.isLoading}
                  dataSource={deployScopeItems}
                  rowKey={(r) => String(asRecord(r)?.runtime_scope_hash)}
                  pagination={false}
                  columns={[
                    { title: "Runtime Scope Hash", dataIndex: "runtime_scope_hash", render: (v: string) => cell(v?.slice(0, 12)) },
                    { title: "Deployment Status", dataIndex: "deployment_status", render: cell },
                    {
                      title: "Scheduler Plan",
                      render: (_: unknown, r: unknown) => `enabled=${String(asRecord(r)?.scheduler_plan_enabled ?? false)}`,
                    },
                    {
                      title: "Operation Status",
                      render: (_: unknown, r: unknown) => {
                        const scopeHash = String(asRecord(r)?.runtime_scope_hash);
                        const isCertified = certifiedScopeHashes.has(scopeHash);
                        return (
                          <Tag color={isCertified ? "success" : "default"}>
                            {isCertified ? "READY_TO_OPERATE" : "NOT_CERTIFIED"}
                          </Tag>
                        );
                      },
                    },
                    {
                      title: "Action",
                      render: (_: unknown, r: unknown) => {
                        const rec = asRecord(r);
                        const scopeHash = String(rec?.runtime_scope_hash);
                        const isCertified = certifiedScopeHashes.has(scopeHash);
                        if (isCertified) return <Typography.Text type="secondary">완료</Typography.Text>;
                        return (
                          <Button
                            size="small"
                            onClick={() => {
                              setOpSelectedScopeHash(scopeHash);
                              setOpSelectedDeploymentReadinessCommitId(Number(rec?.deployment_readiness_commit_id));
                              setOpPackageId(null);
                            }}
                          >
                            Operation Readiness 시작
                          </Button>
                        );
                      },
                    },
                  ]}
                />

                {opSelectedScopeHash != null && opPackageId == null && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      1. Operation Readiness Package 생성
                    </Typography.Title>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      선택된 Runtime Scope: {opSelectedScopeHash}
                    </Typography.Text>
                    <br />
                    <Button
                      onClick={() => createOperationReadinessPackageMutation.mutate()}
                      loading={createOperationReadinessPackageMutation.isPending}
                      disabled={opSelectedDeploymentReadinessCommitId == null}
                    >
                      Operation Readiness Package 생성
                    </Button>
                  </>
                )}

                {opPackage != null && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      2. Certification(15개 영역)
                    </Typography.Title>
                    <Space wrap>
                      <Tag color={opPackage.readiness_status === "READY_FOR_OPERATION" ? "success" : "error"}>
                        {cell(opPackage.readiness_status)}
                      </Tag>
                      <Tag color={opCertification?.all_areas_passed ? "success" : "error"}>
                        All Areas Passed: {String(opCertification?.all_areas_passed ?? false)}
                      </Tag>
                    </Space>
                    <Table
                      size="small"
                      dataSource={Object.entries(opCertificationAreas).map(([area, info]) => ({
                        area, ...(asRecord(info) ?? {}),
                      }))}
                      rowKey="area"
                      pagination={false}
                      columns={[
                        { title: "영역", dataIndex: "area" },
                        {
                          title: "PASS/FAIL",
                          render: (_: unknown, r: unknown) => {
                            const rec = asRecord(r);
                            return <Tag color={rec?.passed ? "success" : "error"}>{rec?.passed ? "PASS" : "FAIL"}</Tag>;
                          },
                        },
                        {
                          title: "Blocking Reason Codes",
                          render: (_: unknown, r: unknown) => extractRows(asRecord(r)?.blocking_reason_codes).join(", "),
                        },
                      ]}
                    />
                    {extractRows(opPackage.blocking_reason_codes).length > 0 && (
                      <Alert
                        type="error"
                        showIcon
                        message="Blocking"
                        description={extractRows(opPackage.blocking_reason_codes).join(", ")}
                      />
                    )}
                    {extractRows(opPackage.warning_reason_codes).length > 0 && (
                      <Alert
                        type="warning"
                        showIcon
                        message="Warning"
                        description={extractRows(opPackage.warning_reason_codes).join(", ")}
                      />
                    )}

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      3. Checklist
                    </Typography.Title>
                    <Space orientation="vertical" size={4} style={{ width: "100%" }}>
                      {opChecklistTemplate.map((row) => {
                        const item = asRecord(row);
                        const code = String(item?.checklist_code ?? "");
                        return (
                          <Space key={code}>
                            <input
                              type="checkbox"
                              checked={Boolean(opChecklistConfirmations[code])}
                              onChange={(e) =>
                                setOpChecklistConfirmations((prev) => ({
                                  ...prev,
                                  [code]: e.target.checked,
                                }))
                              }
                            />
                            <Typography.Text>
                              {cell(item?.question)} {item?.required ? "(필수)" : "(선택)"}
                            </Typography.Text>
                          </Space>
                        );
                      })}
                    </Space>

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      4. Human Decision
                    </Typography.Title>
                    {opDecision == null ? (
                      <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                        <Select
                          style={{ width: 300 }}
                          value={opDecisionType}
                          onChange={(v) => setOpDecisionType(v)}
                          options={[
                            { value: "APPROVE_OPERATION", label: "APPROVE_OPERATION" },
                            { value: "REQUEST_OPERATION_CHANGES", label: "REQUEST_OPERATION_CHANGES" },
                            { value: "REJECT_OPERATION", label: "REJECT_OPERATION" },
                          ]}
                        />
                        <Input
                          placeholder="Reason Code"
                          value={opReasonCode}
                          onChange={(e) => setOpReasonCode(e.target.value)}
                        />
                        <Input
                          placeholder="Reason Text"
                          value={opReasonText}
                          onChange={(e) => setOpReasonText(e.target.value)}
                        />
                        <Space>
                          <input
                            type="checkbox"
                            checked={opWarningsAcknowledged}
                            onChange={(e) => setOpWarningsAcknowledged(e.target.checked)}
                          />
                          <Typography.Text>모든 Warning 확인함</Typography.Text>
                        </Space>
                        <Button
                          onClick={() => recordOperationReadinessDecisionMutation.mutate()}
                          loading={recordOperationReadinessDecisionMutation.isPending}
                          disabled={!opReasonCode.trim() || !opReasonText.trim()}
                        >
                          Decision 기록
                        </Button>
                      </Space>
                    ) : (
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label="Decision Type">{cell(opDecision.decision_type)}</Descriptions.Item>
                        <Descriptions.Item label="Operation Ready">
                          {String(opDecision.operation_ready ?? false)}
                        </Descriptions.Item>
                      </Descriptions>
                    )}

                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      5. Operation Readiness Commit
                    </Typography.Title>
                    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                      <Input
                        placeholder="Commit Reason(필수)"
                        value={opCommitReason}
                        onChange={(e) => setOpCommitReason(e.target.value)}
                      />
                      {Boolean(opDecision?.same_actor_warning) && (
                        <Space>
                          <input
                            type="checkbox"
                            checked={opAcknowledgeSameActorWarning}
                            onChange={(e) => setOpAcknowledgeSameActorWarning(e.target.checked)}
                          />
                          <Typography.Text>Same Actor Warning 확인함</Typography.Text>
                        </Space>
                      )}
                      <Button
                        type="primary"
                        danger
                        disabled={
                          opDecision?.decision_type !== "APPROVE_OPERATION" ||
                          !opDecision?.operation_ready ||
                          !opCommitReason.trim() ||
                          (Boolean(opDecision?.same_actor_warning) && !opAcknowledgeSameActorWarning)
                        }
                        onClick={() => setOpCommitModalOpen(true)}
                      >
                        Operation Readiness Commit 실행
                      </Button>
                    </Space>
                  </>
                )}

                {opHistoryItems.length > 0 && (
                  <>
                    <Typography.Title level={5} style={{ marginTop: 8 }}>
                      Operation Readiness History
                    </Typography.Title>
                    <Table
                      size="small"
                      loading={opHistoryQuery.isLoading}
                      dataSource={opHistoryItems}
                      rowKey={(r) => String(asRecord(r)?.history_id)}
                      pagination={false}
                      columns={[
                        { title: "Event", dataIndex: "event_type", render: cell },
                        { title: "Actor", dataIndex: "actor_id", render: cell },
                        { title: "Occurred At", dataIndex: "occurred_at", render: cell },
                      ]}
                    />
                  </>
                )}
              </Space>
            )}

            <Modal
              title="Operation Readiness Commit 확인"
              open={opCommitModalOpen}
              onCancel={() => setOpCommitModalOpen(false)}
              onOk={() => createOperationReadinessCommitMutation.mutate()}
              okButtonProps={{
                danger: true,
                loading: createOperationReadinessCommitMutation.isPending,
                disabled: opConfirmationText.trim().toUpperCase() !== "OPERATE",
              }}
              okText="Operation Readiness Commit 실행"
            >
              <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                <Typography.Text>
                  이 작업은 같은 Deployment를 READY_TO_OPERATE 상태로만
                  전진시킵니다. Runtime을 시작하지 않습니다.
                </Typography.Text>
                <Typography.Text>
                  Scheduler는 실제로 등록되지 않습니다. Broker 연결/로그인,
                  실시간 시세 구독, 주문 생성/전송은 수행하지 않습니다.
                </Typography.Text>
                <Typography.Text>
                  실제 자동매매 시작(START)은 이 Commit과 별도인 STEP13 운영
                  승인 단계에서 이뤄집니다.
                </Typography.Text>
                <Typography.Text>
                  Operation Readiness Commit은 수정하거나 삭제할 수 없는
                  불변 기록입니다.
                </Typography.Text>
                <Typography.Text strong>계속하려면 OPERATE를 입력하세요.</Typography.Text>
                <Input
                  placeholder="OPERATE"
                  value={opConfirmationText}
                  onChange={(e) => setOpConfirmationText(e.target.value)}
                />
              </Space>
            </Modal>

            <Typography.Title level={5}>Snapshot History</Typography.Title>
            <Table
              size="small"
              loading={snapshotHistoryQuery.isLoading}
              dataSource={snapshotHistoryItems}
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

            <Typography.Title level={5}>Definition Diff</Typography.Title>
            <Space wrap>
              <InputNumber
                placeholder="비교할 Strategy Definition ID"
                value={diffDefinitionId ?? undefined}
                onChange={(v) => setDiffDefinitionId(typeof v === "number" ? v : null)}
                style={{ width: 220 }}
              />
            </Space>
            {diffDefinitionId != null && diffSnapshot != null && (
              <Table
                size="small"
                loading={diffSnapshotQuery.isLoading}
                dataSource={snapshotDiffRows}
                rowKey="field"
                pagination={false}
                columns={[
                  { title: "필드", dataIndex: "field", width: 200 },
                  {
                    title: "상태",
                    dataIndex: "status",
                    width: 100,
                    render: (v: string) => (
                      <Tag color={v === "changed" ? "warning" : "default"}>{v}</Tag>
                    ),
                  },
                  {
                    title: "이 Definition",
                    dataIndex: "before",
                    render: (v: unknown) => cell(JSON.stringify(v)),
                  },
                  {
                    title: `#${diffDefinitionId}`,
                    dataIndex: "after",
                    render: (v: unknown) => cell(JSON.stringify(v)),
                  },
                ]}
              />
            )}
          </Space>
        )}
      </Drawer>
    </AdminPageShell>
  );
}
