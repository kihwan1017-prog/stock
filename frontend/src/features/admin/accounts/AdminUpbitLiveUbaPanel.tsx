"use client";

/**
 * Admin UPBIT LIVE UBA CRUD + Credential + Runtime 제어.
 * LIVE ON/OFF · ARM/DISARM · Trading Scheduler RUN/PAUSE 제공.
 * 실행 순서: Resume 완료 → LIVE ON → ARM ON → Scheduler RUN
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useEffect, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable } from "@/features/admin/components/AdminPanels";
import { cell, extractRows } from "@/features/admin/utils/dataHelpers";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";

function newCorrelationId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Conflict Resolve 실행은 Dry-run 전용 유지 */
const DRY_RUN_ONLY = true;

type RuntimeAction =
  | "LIVE_ON"
  | "LIVE_OFF"
  | "ARM_ON"
  | "ARM_OFF"
  | "SCHEDULER_RUN"
  | "SCHEDULER_PAUSE";

function schedulerIsPaused(status: Record<string, unknown> | undefined): boolean {
  if (!status) return true;
  const desired = String(status.desired_state ?? status.desired ?? "").toUpperCase();
  const actual = String(status.actual_state ?? status.actual ?? "").toUpperCase();
  const desiredPaused = desired === "PAUSE" || desired === "PAUSED" || desired === "";
  const actualPaused =
    actual === "PAUSED" || actual === "PAUSE" || actual === "" || actual === "STOPPED";
  return desiredPaused && actualPaused;
}

function schedulerIsRunning(status: Record<string, unknown> | undefined): boolean {
  if (!status) return false;
  const desired = String(status.desired_state ?? status.desired ?? "").toUpperCase();
  const actual = String(status.actual_state ?? status.actual ?? "").toUpperCase();
  return (
    desired === "RUN" ||
    desired === "RUNNING" ||
    actual === "RUNNING" ||
    actual === "RUN"
  );
}

/** UI gate blockers — 서버 gate와 동일 순서를 화면에서 미리 차단 */
function runtimeGateBlockers(
  action: RuntimeAction,
  row: Record<string, unknown>,
  schedulerPaused: boolean,
  preflightBlocked = false,
): string[] {
  const liveOn = Boolean(row.live_order_enabled);
  const armOn = Boolean(row.live_armed);
  const tradingPaused = Boolean(row.trading_paused);
  const blockers: string[] = [];
  if (action === "LIVE_ON") {
    if (preflightBlocked) {
      blockers.push("Pre-flight READY_FOR_LIVE+FRESH 필요 — LIVE ON 불가");
    }
    if (tradingPaused) blockers.push("거래 일시중지 상태라 LIVE ON 불가");
    if (armOn) blockers.push("ARM 상태라 LIVE ON 불가 — DISARM 후 재시도");
    if (!schedulerPaused) blockers.push("Scheduler 실행 중이라 LIVE ON 불가");
    if (liveOn) blockers.push("이미 LIVE ON");
  }
  if (action === "LIVE_OFF") {
    if (!liveOn) blockers.push("이미 LIVE OFF");
    if (!schedulerPaused) blockers.push("Scheduler 실행 중이라 LIVE OFF 불가");
    if (armOn) blockers.push("ARM 상태라 LIVE OFF 불가 — DISARM 후 재시도");
  }
  if (action === "ARM_ON") {
    if (tradingPaused) blockers.push("거래 일시중지 상태라 ARM 불가");
    if (!liveOn) blockers.push("LIVE OFF라 ARM 불가");
    if (!schedulerPaused) blockers.push("Scheduler 실행 중이라 ARM 불가");
    if (armOn) blockers.push("이미 ARM ON");
  }
  if (action === "ARM_OFF") {
    if (!armOn) blockers.push("이미 DISARM");
    if (!schedulerPaused) blockers.push("Scheduler 실행 중이라 DISARM 불가");
  }
  if (action === "SCHEDULER_RUN") {
    if (tradingPaused) blockers.push("거래 일시중지 상태라 Scheduler RUN 불가");
    if (!liveOn) blockers.push("LIVE OFF라 Scheduler RUN 불가");
    if (!armOn) blockers.push("ARM OFF라 Scheduler RUN 불가");
    // active strategy link는 허용 — Runtime RUNNING만 주문 경로
  }
  return blockers;
}

export function AdminUpbitLiveUbaPanel() {
  const { message: messageApi, modal } = App.useApp();
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [credTarget, setCredTarget] = useState<number | null>(null);
  const [editTarget, setEditTarget] = useState<Record<string, unknown> | null>(
    null,
  );
  const [detailUbaId, setDetailUbaId] = useState<number | null>(null);
  const [selectedConflictIds, setSelectedConflictIds] = useState<number[]>([]);
  const [dryRunResult, setDryRunResult] = useState<Record<string, unknown> | null>(null);
  const [resumeCheck, setResumeCheck] = useState<Record<string, unknown> | null>(null);
  const [createForm] = Form.useForm();
  const [credForm] = Form.useForm();
  const [editForm] = Form.useForm();

  // Modal.confirm / mutation 콜백이 렌더 경로와 겹치면 antd Message 경고 발생 → 다음 틱으로 미룸
  const notifySuccess = (text: string) => {
    queueMicrotask(() => {
      messageApi.success(text);
    });
  };
  const notifyError = (err: unknown) => {
    queueMicrotask(() => {
      messageApi.error(toApiError(err).message);
    });
  };

  const listQuery = useQuery({
    queryKey: ["admin", "broker-accounts", "UPBIT"],
    queryFn: () =>
      adminApi.listAdminBrokerAccounts({
        broker_code: "UPBIT",
        include_inactive: true,
        limit: 100,
      }),
  });

  const readinessQuery = useQuery({
    queryKey: ["admin", "live-ops-readiness"],
    queryFn: adminApi.getAdminLiveOpsReadiness,
  });

  const autotradingReadyQuery = useQuery({
    queryKey: ["admin", "autotrading-readiness", detailUbaId],
    queryFn: () =>
      adminApi.getAdminUbaAutotradingReadiness(Number(detailUbaId)),
    enabled: detailUbaId != null,
  });

  const liveOutboxWorkerQuery = useQuery({
    queryKey: ["admin", "live-outbox-worker-status"],
    queryFn: adminApi.getAdminLiveOutboxWorkerStatus,
  });

  const tradingSchedulerQuery = useQuery({
    queryKey: ["admin", "trading-scheduler", "status"],
    queryFn: adminApi.getTradingSchedulerStatus,
    refetchInterval: 15_000,
  });

  const preflightQuery = useQuery({
    queryKey: queryKeys.admin.runtimePreflight(),
    queryFn: () => adminApi.getRuntimePreflight({ mode: "LIVE_ON" }),
    refetchInterval: 15_000,
  });
  // Pre-flight TTL(60s) 만료 시 LIVE ON 비활성 갱신
  const [preflightNowMs, setPreflightNowMs] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setPreflightNowMs(Date.now()), 5_000);
    return () => window.clearInterval(id);
  }, []);

  const opsQuery = useQuery({
    queryKey: ["admin", "broker-accounts", "ops", detailUbaId],
    queryFn: () =>
      adminApi.getAdminBrokerAccountOpsStatus(Number(detailUbaId)),
    enabled: detailUbaId != null,
  });

  const invalidate = async () => {
    await queryClient.invalidateQueries({
      queryKey: ["admin", "broker-accounts", "UPBIT"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "live-ops-readiness"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "trading-scheduler", "status"],
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.admin.runtimePreflight(),
    });
    if (detailUbaId != null) {
      await queryClient.invalidateQueries({
        queryKey: ["admin", "broker-accounts", "ops", detailUbaId],
      });
    }
  };

  const createMutation = useMutation({
    mutationFn: adminApi.createAdminBrokerAccount,
    onSuccess: async () => {
      notifySuccess("UPBIT UBA 생성 완료 (LIVE OFF, 권장 Risk 적용)");
      setCreateOpen(false);
      createForm.resetFields();
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      ubaId,
      body,
    }: {
      ubaId: number;
      body: { account_alias?: string; is_active?: boolean };
    }) => adminApi.updateAdminBrokerAccount(ubaId, body),
    onSuccess: async () => {
      notifySuccess("UBA 수정 완료");
      setEditTarget(null);
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const deleteMutation = useMutation({
    mutationFn: adminApi.deleteAdminBrokerAccount,
    onSuccess: async () => {
      notifySuccess("UBA 연결 삭제 완료 (LIVE OFF 강제)");
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const riskMutation = useMutation({
    mutationFn: adminApi.applyAdminBrokerRecommendedRisk,
    onSuccess: async () => {
      notifySuccess(
        "권장 Risk 적용 (주문 5000 / 비율·일손실·포지션 한도 포함)",
      );
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const registerCredMutation = useMutation({
    mutationFn: ({
      ubaId,
      body,
    }: {
      ubaId: number;
      body: { access_key: string; secret_key: string };
    }) => adminApi.registerAdminBrokerCredential(ubaId, body),
    onSuccess: async () => {
      notifySuccess("Credential 등록 요청 완료 (원문 미보관 UI)");
      setCredTarget(null);
      credForm.resetFields();
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const replaceCredMutation = useMutation({
    mutationFn: ({
      ubaId,
      body,
    }: {
      ubaId: number;
      body: { access_key: string; secret_key: string };
    }) => adminApi.replaceAdminBrokerCredential(ubaId, body),
    onSuccess: async () => {
      notifySuccess("Credential 교체 완료");
      setCredTarget(null);
      credForm.resetFields();
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const resumeMutation = useMutation({
    mutationFn: (ubaId: number) =>
      adminApi.resumeRecoveryAccount(ubaId, {
        reason: "admin_resume_trading",
        correlation_id: newCorrelationId("resolve"),
      }),
    onSuccess: async () => {
      notifySuccess("Resume Trading 완료");
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const conflictSummaryQuery = useQuery({
    queryKey: ["admin", "recovery", "conflict-summary", detailUbaId],
    queryFn: () => adminApi.getRecoveryConflictSummary(Number(detailUbaId)),
    enabled: detailUbaId != null,
  });

  const dryRunMutation = useMutation({
    mutationFn: (payload: {
      ubaId: number;
      conflict_ids: number[];
      resolution: string;
      reason: string;
    }) =>
      adminApi.dryRunResolveRecoveryConflicts(payload.ubaId, {
        conflict_ids: payload.conflict_ids,
        resolution: payload.resolution,
        reason: payload.reason,
        expected_status: "PENDING_REVIEW",
      }),
    onSuccess: (data) => {
      setDryRunResult(data as Record<string, unknown>);
      notifySuccess("Dry-run 완료 (DB 변경 없음)");
    },
    onError: (err) => notifyError(err),
  });

  const resumeCheckMutation = useMutation({
    mutationFn: (ubaId: number) => adminApi.getRecoveryResumeCheck(ubaId),
    onSuccess: (data) => {
      setResumeCheck(data as Record<string, unknown>);
      notifySuccess("Resume 사전 점검 완료 (상태 변경 없음)");
    },
    onError: (err) => notifyError(err),
  });

  const retryRecoveryMutation = useMutation({
    mutationFn: (ubaId: number) =>
      adminApi.runAdminAccountRecovery(ubaId, "UPBIT"),
    onSuccess: async () => {
      notifySuccess("Retry Recovery 요청 완료");
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const unlockMutation = useMutation({
    mutationFn: (ubaId: number) =>
      adminApi.unlockRecoveryAccount(ubaId, {
        note: "admin_unlock_account",
      }),
    onSuccess: async () => {
      notifySuccess("Unlock Account 완료 (account_paused=false)");
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const refreshRuntimeMutation = useMutation({
    mutationFn: (ubaId: number) =>
      adminApi.refreshAdminUbaSnapshot(ubaId, "admin_refresh_runtime"),
    onSuccess: async () => {
      notifySuccess("Refresh Runtime(snapshot) 완료");
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const runtimeControlMutation = useMutation({
    mutationFn: async (args: {
      action: RuntimeAction;
      ubaId: number;
      reason: string;
    }) => {
      const correlationId = newCorrelationId(args.action.toLowerCase());
      switch (args.action) {
        case "LIVE_ON":
          return adminApi.setAdminLiveOrderEnabled(args.ubaId, true, {
            reason: args.reason,
            correlation_id: correlationId,
          });
        case "LIVE_OFF":
          return adminApi.setAdminLiveOrderEnabled(args.ubaId, false, {
            reason: args.reason,
            correlation_id: correlationId,
          });
        case "ARM_ON":
          return adminApi.armAdminLiveOrder(args.ubaId, {
            reason: args.reason,
            correlation_id: correlationId,
          });
        case "ARM_OFF":
          return adminApi.disarmAdminLiveOrder(args.ubaId, {
            turn_live_off: false,
            reason: args.reason,
            correlation_id: correlationId,
          });
        case "SCHEDULER_RUN":
          return adminApi.startTradingScheduler({
            reason: args.reason,
            correlation_id: correlationId,
            user_broker_account_id: args.ubaId,
          });
        case "SCHEDULER_PAUSE":
          return adminApi.pauseTradingScheduler({
            reason: args.reason,
            correlation_id: correlationId,
            user_broker_account_id: args.ubaId,
          });
        default:
          throw new Error(`unknown runtime action: ${String(args.action)}`);
      }
    },
    onSuccess: async (_data, vars) => {
      notifySuccess(`${vars.action} 완료 (UBA ${vars.ubaId})`);
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

  const rows = extractRows(listQuery.data) as Record<string, unknown>[];
  const readiness = readinessQuery.data as
    | {
        dry_run_ready?: boolean;
        blockers?: string[];
        warnings?: string[];
        schedulers?: {
          trading?: { running?: boolean | null; ok?: boolean };
          tracking?: { enabled?: boolean; ok?: boolean };
          post_fill?: { enabled?: boolean; ok?: boolean };
        };
        upbit_use_mock?: boolean;
      }
    | undefined;

  const tradingSchedulerStatus = tradingSchedulerQuery.data as
    | Record<string, unknown>
    | undefined;
  const schedulerPaused = schedulerIsPaused(tradingSchedulerStatus);
  const schedulerRunning = schedulerIsRunning(tradingSchedulerStatus);
  const preflightLiveOnAllowed = adminApi.isPreflightLiveOnAllowed(
    preflightQuery.data,
    preflightNowMs,
  );
  const preflightFreshness = adminApi.evaluatePreflightFreshness(
    preflightQuery.data?.checked_at ??
      preflightQuery.data?.freshness?.checked_at,
    Number(preflightQuery.data?.freshness?.ttl_seconds) ||
      adminApi.PREFLIGHT_TTL_SECONDS,
    preflightNowMs,
  );
  // LIVE ON UI: READY_FOR_LIVE + FRESH 만 허용 (서버도 Pre-flight 재검증)
  const preflightBlocked = !preflightLiveOnAllowed;

  const confirmRuntimeAction = (
    action: RuntimeAction,
    ubaId: number,
    row: Record<string, unknown>,
  ) => {
    const liveOn = Boolean(row.live_order_enabled);
    const armOn = Boolean(row.live_armed);
    const tradingPaused = Boolean(row.trading_paused);

    // 실행 순서 강제: Resume → LIVE ON → ARM ON → Scheduler RUN
    if (action === "LIVE_ON") {
      if (preflightBlocked) {
        messageApi.error(
          preflightFreshness.status === "STALE"
            ? "Pre-flight 결과가 STALE(60초 초과)입니다. 재검사 후 LIVE ON 하세요."
            : "Pre-flight Check 가 READY_FOR_LIVE 가 아니라 LIVE ON 불가합니다.",
        );
        return;
      }
      if (tradingPaused) {
        messageApi.error("Resume 완료(거래 일시중지 해제) 후 LIVE ON 가능합니다.");
        return;
      }
      if (armOn) {
        messageApi.error("ARM이 ON이면 LIVE ON을 실행할 수 없습니다. DISARM 후 재시도하세요.");
        return;
      }
      if (!schedulerPaused) {
        messageApi.error("Scheduler가 PAUSE 상태일 때만 LIVE ON 가능합니다.");
        return;
      }
    }
    if (action === "ARM_ON") {
      if (tradingPaused) {
        messageApi.error("Resume 완료 후 ARM ON 가능합니다.");
        return;
      }
      if (!liveOn) {
        messageApi.error("LIVE OFF 상태에서는 ARM ON을 실행할 수 없습니다.");
        return;
      }
      if (!schedulerPaused) {
        messageApi.error("Scheduler가 PAUSE 상태일 때만 ARM ON 가능합니다.");
        return;
      }
    }
    if (action === "SCHEDULER_RUN") {
      if (tradingPaused) {
        messageApi.error("Resume 완료 후 Scheduler RUN 가능합니다.");
        return;
      }
      if (!liveOn) {
        messageApi.error("LIVE OFF 상태에서는 Scheduler RUN을 실행할 수 없습니다.");
        return;
      }
      if (!armOn) {
        messageApi.error("ARM OFF 상태에서는 Scheduler RUN을 실행할 수 없습니다.");
        return;
      }
    }
    if (action === "ARM_OFF" && !schedulerPaused) {
      messageApi.error("Scheduler PAUSE 후 DISARM 가능합니다.");
      return;
    }
    if (action === "LIVE_OFF") {
      if (!schedulerPaused) {
        messageApi.error("Scheduler PAUSE 후 LIVE OFF 가능합니다.");
        return;
      }
      if (armOn) {
        messageApi.error("DISARM 후 LIVE OFF 가능합니다.");
        return;
      }
    }

    const titles: Record<RuntimeAction, string> = {
      LIVE_ON: "실거래를 활성화하시겠습니까?",
      LIVE_OFF: "LIVE를 비활성화하시겠습니까?",
      ARM_ON: "실거래를 활성화하시겠습니까?",
      ARM_OFF: "ARM을 해제하시겠습니까?",
      SCHEDULER_RUN: "실거래를 활성화하시겠습니까?",
      SCHEDULER_PAUSE: "Trading Scheduler를 PAUSE 하시겠습니까?",
    };
    const reasons: Record<RuntimeAction, string> = {
      LIVE_ON: "ADMIN_UI_LIVE_ON",
      LIVE_OFF: "ADMIN_UI_LIVE_OFF",
      ARM_ON: "ADMIN_UI_ARM_ON",
      ARM_OFF: "ADMIN_UI_ARM_OFF",
      SCHEDULER_RUN: "ADMIN_UI_SCHEDULER_RUN",
      SCHEDULER_PAUSE: "ADMIN_UI_SCHEDULER_PAUSE",
    };

    modal.confirm({
      title: titles[action],
      content: (
        <Space orientation="vertical" size={4}>
          <Typography.Text>
            UBA {ubaId} · 동작: {action}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            순서: Resume → LIVE ON → ARM ON → Scheduler RUN
          </Typography.Text>
        </Space>
      ),
      okText: "실행",
      cancelText: "취소",
      okButtonProps: {
        danger: action === "LIVE_ON" || action === "ARM_ON" || action === "SCHEDULER_RUN",
      },
      onOk: () =>
        runtimeControlMutation.mutateAsync({
          action,
          ubaId,
          reason: reasons[action],
        }),
    });
  };

  const ops = opsQuery.data as Record<string, unknown> | undefined;

  return (
    <Card
      title="UPBIT LIVE UBA (STEP 8-9C)"
      size="small"
      extra={
        <Space wrap>
          <Button onClick={() => void listQuery.refetch()}>새로고침</Button>
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            UBA 생성
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="Runtime 제어: Resume 완료 → LIVE ON → ARM ON → Scheduler RUN 순서만 허용됩니다."
        description="실주문 버튼은 없습니다. OFF/PAUSE는 역순(Scheduler PAUSE → DISARM → LIVE OFF)입니다."
      />
      <Alert
        type={preflightLiveOnAllowed ? "success" : "warning"}
        showIcon
        style={{ marginBottom: 12 }}
        title={`Pre-flight: ${String(preflightQuery.data?.overall_status ?? "LOADING")} · ${preflightFreshness.status}`}
        description={
          preflightLiveOnAllowed
            ? "READY_FOR_LIVE + FRESH — LIVE ON UI 활성 (서버도 Pre-flight 재검증)"
            : "LIVE ON은 Pre-flight READY_FOR_LIVE 이고 60초 이내(FRESH)일 때만 활성화됩니다."
        }
      />

      {readiness ? (
        <Alert
          type={readiness.dry_run_ready ? "success" : "warning"}
          showIcon
          style={{ marginBottom: 12 }}
          title={`Live-ops readiness: ${
            readiness.dry_run_ready ? "OK" : "BLOCKED"
          }`}
          description={
            <Space orientation="vertical" size={4}>
              <Typography.Text>
                Trading Scheduler:{" "}
                {schedulerRunning
                  ? "RUN"
                  : schedulerPaused
                    ? "PAUSE"
                    : String(
                        tradingSchedulerStatus?.desired_state ??
                          readiness.schedulers?.trading?.running ??
                          "-",
                      )}
              </Typography.Text>
              {(readiness.blockers ?? []).length > 0 ? (
                <Typography.Text type="danger">
                  blockers: {(readiness.blockers ?? []).join(", ")}
                </Typography.Text>
              ) : null}
            </Space>
          }
        />
      ) : null}

      {detailUbaId != null && autotradingReadyQuery.data ? (
        <Alert
          type={
            (autotradingReadyQuery.data as { status?: string }).status ===
            "READY_FOR_AUTO_TRADING"
              ? "success"
              : "warning"
          }
          showIcon
          style={{ marginBottom: 12 }}
          title={`Auto Trading: ${String(
            (autotradingReadyQuery.data as { status?: string }).status ??
              "BLOCKED",
          )}`}
          description={
            <Space orientation="vertical" size={4}>
              <Typography.Text>
                UBA {detailUbaId} · Runtime{" "}
                {String(
                  (autotradingReadyQuery.data as { runtime_status?: string })
                    .runtime_status ?? "-",
                )}{" "}
                · Worker{" "}
                {liveOutboxWorkerQuery.data
                  ? `${
                      (liveOutboxWorkerQuery.data as { enabled?: boolean })
                        .enabled
                        ? "ENABLED"
                        : "DISABLED"
                    }/${
                      (liveOutboxWorkerQuery.data as { running?: boolean })
                        .running
                        ? "RUN"
                        : "STOP"
                    }`
                  : "-"}
              </Typography.Text>
              <Typography.Text type="secondary">
                시작 버튼 비활성 (이번 STEP). 운영 ON은 별도 승인 후.
              </Typography.Text>
              {(
                (autotradingReadyQuery.data as { blockers?: string[] })
                  .blockers ?? []
              ).length > 0 ? (
                <Typography.Text type="danger">
                  blockers:{" "}
                  {(
                    (autotradingReadyQuery.data as { blockers?: string[] })
                      .blockers ?? []
                  ).join(", ")}
                </Typography.Text>
              ) : null}
              {(() => {
                const ctx = (
                  autotradingReadyQuery.data as {
                    checks?: {
                      market_context?: {
                        ai_analysis_job?: {
                          enabled?: boolean;
                          running?: boolean;
                          interval_seconds?: number;
                          provider?: string;
                          model?: string;
                          last_run_at?: string | null;
                          next_run_at?: string | null;
                          last_success_at?: string | null;
                          last_failure_at?: string | null;
                          last_error?: string | null;
                          run_count?: number;
                          success_count?: number;
                          failure_count?: number;
                        };
                        latest_analysis?: {
                          status?: string;
                          fresh?: boolean;
                          age_seconds?: number | null;
                          analysis_at?: string | null;
                          recommendation?: string | null;
                          confidence?: number | string | null;
                          risk_level?: string | null;
                          news_sentiment?: string | null;
                          provider?: string | null;
                          model?: string | null;
                          reasons?: string[] | null;
                          summary?: string | null;
                        };
                      };
                      ai_signal_gate?: {
                        enabled?: boolean;
                        stale?: boolean;
                        age_seconds?: number | null;
                        latest?: {
                          recommendation?: string | null;
                          confidence?: number | string | null;
                          news_sentiment?: string | null;
                          provider?: string | null;
                          model?: string | null;
                          analysis_at?: string | null;
                        } | null;
                        live_fail_closed?: boolean;
                      };
                    };
                  }
                ).checks;
                const ai = ctx?.ai_signal_gate;
                const latest =
                  ctx?.market_context?.latest_analysis ??
                  (ai?.latest
                    ? {
                        status: ai.latest.recommendation
                          ? "AI_ANALYSIS_FOUND"
                          : "AI_ANALYSIS_MISSING",
                        fresh: ai.stale === false,
                        ...ai.latest,
                      }
                    : null);
                const job = ctx?.market_context?.ai_analysis_job;
                if (!ai && !latest && !job) return null;
                const reasons = Array.isArray(latest?.reasons)
                  ? latest?.reasons?.slice(0, 3).join("; ")
                  : latest?.summary
                    ? String(latest.summary).slice(0, 120)
                    : "-";
                return (
                  <Space orientation="vertical" size={2}>
                    <Typography.Text type="secondary">
                      AI Analysis Job:{" "}
                      {job?.enabled ? "ON" : "OFF"}
                      {job?.running ? "/RUN" : ""}
                      {" · "}
                      interval: {job?.interval_seconds ?? "-"}s
                      {" · "}
                      {job?.provider ?? latest?.provider ?? "-"}/
                      {job?.model ?? latest?.model ?? "-"}
                      {" · "}
                      last: {job?.last_run_at ?? "-"}
                      {" · "}
                      next: {job?.next_run_at ?? "-"}
                      {" · "}
                      ok: {job?.last_success_at ?? "-"}
                      {" · "}
                      fail: {job?.last_failure_at ?? job?.last_error ?? "-"}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      Last analysis: {latest?.analysis_at ?? "-"}
                      {" · "}
                      {latest?.status ?? "-"}
                      {" · "}
                      freshness:{" "}
                      {latest?.fresh
                        ? `OK (${Math.round(Number(latest.age_seconds ?? 0))}s)`
                        : ai?.stale
                          ? "STALE"
                          : "N/A"}
                      {" · "}
                      rec: {latest?.recommendation ?? "-"}
                      {" · "}
                      conf: {String(latest?.confidence ?? "-")}
                      {" · "}
                      risk: {latest?.risk_level ?? "-"}
                      {" · "}
                      news: {latest?.news_sentiment ?? "-"}
                    </Typography.Text>
                    <Typography.Text type="secondary">
                      AI Gate: {ai?.enabled ? "ON" : "OFF"}
                      {" · "}
                      LIVE Gate:{" "}
                      {(ai as { live_enabled?: boolean } | undefined)
                        ?.live_enabled
                        ? "ON"
                        : "OFF"}
                      {" · "}
                      fail-closed: {ai?.live_fail_closed ? "YES" : "NO"}
                      {" · "}
                      reasons: {reasons}
                    </Typography.Text>
                  </Space>
                );
              })()}
            </Space>
          }
        />
      ) : null}

      <AdminDataTable
        loading={listQuery.isLoading}
        dataSource={rows}
        rowKey={(row) =>
          String(row.user_broker_account_id ?? row.account_id ?? Math.random())
        }
        columns={[
          {
            title: "UBA",
            width: 80,
            render: (_: unknown, row) =>
              cell(row.user_broker_account_id ?? row.account_id),
          },
          {
            title: "Owner",
            dataIndex: "user_id",
            width: 80,
            render: (_: unknown, row) => cell(row.user_id),
          },
          {
            title: "Alias",
            dataIndex: "account_name",
            render: (_: unknown, row) => cell(row.account_name),
          },
          {
            title: "Conn",
            dataIndex: "connection_status",
            width: 120,
            render: (_: unknown, row) => cell(row.connection_status),
          },
          {
            title: "Paused",
            width: 80,
            render: (_: unknown, row) =>
              row.trading_paused ? (
                <Tag color="red">Y</Tag>
              ) : (
                <Tag>N</Tag>
              ),
          },
          {
            title: "Recovery",
            width: 110,
            render: (_: unknown, row) => cell(row.recovery_status),
          },
          {
            title: "LIVE",
            key: "live_control",
            width: 150,
            render: (_: unknown, row) => {
              const ubaId = Number(row.user_broker_account_id ?? row.account_id);
              const liveOn = Boolean(row.live_order_enabled);
              const onBlockers = runtimeGateBlockers(
                "LIVE_ON",
                row,
                schedulerPaused,
                preflightBlocked,
              );
              const offBlockers = runtimeGateBlockers(
                "LIVE_OFF",
                row,
                schedulerPaused,
              );
              const onBusy =
                runtimeControlMutation.isPending &&
                runtimeControlMutation.variables?.action === "LIVE_ON" &&
                runtimeControlMutation.variables?.ubaId === ubaId;
              const offBusy =
                runtimeControlMutation.isPending &&
                runtimeControlMutation.variables?.action === "LIVE_OFF" &&
                runtimeControlMutation.variables?.ubaId === ubaId;
              return (
                <Space orientation="vertical" size={2}>
                  <Tag color={liveOn ? "green" : "default"}>
                    {liveOn ? "ON" : "OFF"}
                  </Tag>
                  <Space size={4}>
                    <Tooltip
                      title={
                        onBlockers.length
                          ? onBlockers.join(" · ")
                          : "LIVE ON"
                      }
                    >
                      <Button
                        size="small"
                        type="primary"
                        loading={onBusy}
                        disabled={
                          onBlockers.length > 0 ||
                          runtimeControlMutation.isPending
                        }
                        onClick={() =>
                          confirmRuntimeAction("LIVE_ON", ubaId, row)
                        }
                      >
                        ON
                      </Button>
                    </Tooltip>
                    <Tooltip
                      title={
                        offBlockers.length
                          ? offBlockers.join(" · ")
                          : "LIVE OFF"
                      }
                    >
                      <Button
                        size="small"
                        danger
                        loading={offBusy}
                        disabled={
                          offBlockers.length > 0 ||
                          runtimeControlMutation.isPending
                        }
                        onClick={() =>
                          confirmRuntimeAction("LIVE_OFF", ubaId, row)
                        }
                      >
                        OFF
                      </Button>
                    </Tooltip>
                  </Space>
                </Space>
              );
            },
          },
          {
            title: "ARM",
            key: "arm_control",
            width: 160,
            render: (_: unknown, row) => {
              const ubaId = Number(row.user_broker_account_id ?? row.account_id);
              const armOn = Boolean(row.live_armed);
              const onBlockers = runtimeGateBlockers(
                "ARM_ON",
                row,
                schedulerPaused,
              );
              const offBlockers = runtimeGateBlockers(
                "ARM_OFF",
                row,
                schedulerPaused,
              );
              const onBusy =
                runtimeControlMutation.isPending &&
                runtimeControlMutation.variables?.action === "ARM_ON" &&
                runtimeControlMutation.variables?.ubaId === ubaId;
              const offBusy =
                runtimeControlMutation.isPending &&
                runtimeControlMutation.variables?.action === "ARM_OFF" &&
                runtimeControlMutation.variables?.ubaId === ubaId;
              return (
                <Space orientation="vertical" size={2}>
                  <Tag color={armOn ? "orange" : "default"}>
                    {armOn ? "Y" : "N"}
                  </Tag>
                  <Space size={4}>
                    <Tooltip
                      title={
                        onBlockers.length
                          ? onBlockers.join(" · ")
                          : "ARM ON"
                      }
                    >
                      <Button
                        size="small"
                        type="primary"
                        loading={onBusy}
                        disabled={
                          onBlockers.length > 0 ||
                          runtimeControlMutation.isPending
                        }
                        onClick={() =>
                          confirmRuntimeAction("ARM_ON", ubaId, row)
                        }
                      >
                        ARM
                      </Button>
                    </Tooltip>
                    <Tooltip
                      title={
                        offBlockers.length
                          ? offBlockers.join(" · ")
                          : "DISARM"
                      }
                    >
                      <Button
                        size="small"
                        danger
                        loading={offBusy}
                        disabled={
                          offBlockers.length > 0 ||
                          runtimeControlMutation.isPending
                        }
                        onClick={() =>
                          confirmRuntimeAction("ARM_OFF", ubaId, row)
                        }
                      >
                        DISARM
                      </Button>
                    </Tooltip>
                  </Space>
                </Space>
              );
            },
          },
          {
            title: "Scheduler",
            key: "scheduler_control",
            width: 170,
            render: (_: unknown, row) => {
              const ubaId = Number(row.user_broker_account_id ?? row.account_id);
              const runBlockers = runtimeGateBlockers(
                "SCHEDULER_RUN",
                row,
                schedulerPaused,
              );
              const pauseBlockers = schedulerPaused
                ? ["이미 Scheduler PAUSE"]
                : [];
              const runBusy =
                runtimeControlMutation.isPending &&
                runtimeControlMutation.variables?.action === "SCHEDULER_RUN";
              const pauseBusy =
                runtimeControlMutation.isPending &&
                runtimeControlMutation.variables?.action === "SCHEDULER_PAUSE";
              return (
                <Space orientation="vertical" size={2}>
                  <Tag color={schedulerRunning ? "red" : "default"}>
                    {schedulerRunning ? "RUN" : "PAUSE"}
                  </Tag>
                  <Space size={4}>
                    <Tooltip
                      title={
                        runBlockers.length
                          ? runBlockers.join(" · ")
                          : "Scheduler RUN"
                      }
                    >
                      <Button
                        size="small"
                        type="primary"
                        danger
                        loading={runBusy}
                        disabled={
                          runBlockers.length > 0 ||
                          schedulerRunning ||
                          runtimeControlMutation.isPending
                        }
                        onClick={() =>
                          confirmRuntimeAction("SCHEDULER_RUN", ubaId, row)
                        }
                      >
                        RUN
                      </Button>
                    </Tooltip>
                    <Tooltip
                      title={
                        pauseBlockers.length
                          ? pauseBlockers.join(" · ")
                          : "Scheduler PAUSE"
                      }
                    >
                      <Button
                        size="small"
                        loading={pauseBusy}
                        disabled={
                          pauseBlockers.length > 0 ||
                          runtimeControlMutation.isPending
                        }
                        onClick={() =>
                          confirmRuntimeAction("SCHEDULER_PAUSE", ubaId, row)
                        }
                      >
                        PAUSE
                      </Button>
                    </Tooltip>
                  </Space>
                </Space>
              );
            },
          },
          {
            title: "Cred",
            key: "cred",
            width: 90,
            render: (_: unknown, row) => {
              const cred = row.credential as
                | { registered?: boolean; verification_status?: string }
                | undefined;
              return cred?.registered
                ? String(cred.verification_status ?? "Y")
                : "N";
            },
          },
          {
            title: "Actions",
            key: "actions",
            width: 520,
            render: (_: unknown, row) => {
              const ubaId = Number(row.user_broker_account_id ?? row.account_id);
              const registered = Boolean(
                (row.credential as { registered?: boolean } | undefined)
                  ?.registered,
              );
              return (
                <Space wrap size={4}>
                  <Button size="small" onClick={() => setDetailUbaId(ubaId)}>
                    상세
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      setEditTarget(row);
                    }}
                  >
                    수정
                  </Button>
                  <Button
                    size="small"
                    onClick={() => setCredTarget(ubaId)}
                  >
                    {registered ? "Credential 교체" : "Credential 등록"}
                  </Button>
                  <Button
                    size="small"
                    loading={riskMutation.isPending}
                    onClick={() => riskMutation.mutate(ubaId)}
                  >
                    Risk 5000
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    loading={resumeCheckMutation.isPending || resumeMutation.isPending}
                    onClick={() => {
                      if (DRY_RUN_ONLY) {
                        resumeCheckMutation.mutate(ubaId);
                        setDetailUbaId(ubaId);
                        return;
                      }
                      modal.confirm({
                        title: "Resume Trading",
                        content:
                          "LIVE/ARM은 변경되지 않습니다. 거래를 재개할까요?",
                        onOk: () => resumeMutation.mutateAsync(ubaId),
                      });
                    }}
                  >
                    {DRY_RUN_ONLY ? "Resume 사전 점검" : "Resume Trading"}
                  </Button>
                  <Button
                    size="small"
                    onClick={() => {
                      setDetailUbaId(ubaId);
                      setSelectedConflictIds([]);
                      setDryRunResult(null);
                      setResumeCheck(null);
                    }}
                  >
                    Conflict 검토
                  </Button>
                  <Button
                    size="small"
                    loading={retryRecoveryMutation.isPending}
                    onClick={() => retryRecoveryMutation.mutate(ubaId)}
                  >
                    Retry Recovery
                  </Button>
                  <Button
                    size="small"
                    loading={unlockMutation.isPending}
                    onClick={() => unlockMutation.mutate(ubaId)}
                  >
                    Unlock Account
                  </Button>
                  <Button
                    size="small"
                    loading={refreshRuntimeMutation.isPending}
                    onClick={() => refreshRuntimeMutation.mutate(ubaId)}
                  >
                    Refresh Runtime
                  </Button>
                  <Button
                    size="small"
                    danger
                    onClick={() => {
                      modal.confirm({
                        title: "UBA 연결 삭제",
                        content:
                          "Broker 연결 행만 삭제합니다. LIVE OFF 후 unlink. 실계좌는 삭제되지 않습니다.",
                        okType: "danger",
                        onOk: () => deleteMutation.mutateAsync(ubaId),
                      });
                    }}
                  >
                    삭제
                  </Button>
                </Space>
              );
            },
          },
        ]}
      />

      <Drawer
        title={`UBA 운영 상세 #${detailUbaId ?? ""}`}
        open={detailUbaId != null}
        onClose={() => setDetailUbaId(null)}
        size={560}
      >
        {opsQuery.isLoading ? (
          <Typography.Text>로딩 중…</Typography.Text>
        ) : opsQuery.error ? (
          <Alert type="error" title={toApiError(opsQuery.error).message} />
        ) : ops ? (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title="DRY-RUN ONLY 모드"
              description="이번 단계에서는 Conflict 실제 해제·Resume 실행이 비활성화되어 있습니다. Dry-run / 사전 점검만 가능합니다. LIVE/ARM은 변경되지 않습니다."
            />
            <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="Conflict Code">
              {cell(ops.conflict_code)}
            </Descriptions.Item>
            <Descriptions.Item label="Conflict Reason">
              {cell(ops.conflict_reason)}
            </Descriptions.Item>
            <Descriptions.Item label="Paused Reason">
              {cell(ops.paused_reason)}
            </Descriptions.Item>
            <Descriptions.Item label="Recovery Status">
              {cell(ops.recovery_status)}
            </Descriptions.Item>
            <Descriptions.Item label="Trading Paused">
              {String(ops.trading_paused ?? "-")}
            </Descriptions.Item>
            <Descriptions.Item label="Credential Status">
              {cell(ops.credential_status)}
            </Descriptions.Item>
            <Descriptions.Item label="Connection Status">
              {cell(ops.connection_status)}
            </Descriptions.Item>
            <Descriptions.Item label="LIVE / ARM">
              {String(ops.live_order_enabled ? "ON" : "OFF")} /{" "}
              {String(ops.live_armed ? "Y" : "N")}
            </Descriptions.Item>
            <Descriptions.Item label="Active Conflicts">
              {cell(ops.active_conflict_count)}
            </Descriptions.Item>
            </Descriptions>

            {conflictSummaryQuery.data ? (
              <Descriptions
                title="Conflict 요약"
                column={1}
                size="small"
                bordered
              >
                <Descriptions.Item label="전체 활성">
                  {cell(
                    (conflictSummaryQuery.data as Record<string, unknown>)
                      .active_conflict_count,
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="IGNORE 가능 후보">
                  {cell(
                    (conflictSummaryQuery.data as Record<string, unknown>)
                      .ignore_candidates,
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="원격 체결 보존 필요">
                  {cell(
                    (conflictSummaryQuery.data as Record<string, unknown>)
                      .preserve_remote_history_needed,
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="해제 불가">
                  {cell(
                    (conflictSummaryQuery.data as Record<string, unknown>)
                      .blocked_count,
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="유형별">
                  {JSON.stringify(
                    (conflictSummaryQuery.data as Record<string, unknown>)
                      .by_type ?? {},
                  )}
                </Descriptions.Item>
              </Descriptions>
            ) : null}

            <Table
              size="small"
              rowKey="conflict_id"
              loading={conflictSummaryQuery.isLoading}
              pagination={{ pageSize: 10 }}
              dataSource={
                ((
                  (conflictSummaryQuery.data as Record<string, unknown> | undefined)
                    ?.items as Record<string, unknown>[] | undefined
                ) ?? [])
              }
              rowSelection={{
                selectedRowKeys: selectedConflictIds,
                onChange: (keys) =>
                  setSelectedConflictIds(keys.map((k) => Number(k))),
                getCheckboxProps: (record) => ({
                  disabled: !Boolean(record.eligible_for_ignore),
                }),
              }}
              columns={[
                { title: "ID", dataIndex: "conflict_id", width: 70 },
                { title: "유형", dataIndex: "conflict_type", width: 160, ellipsis: true },
                {
                  title: "원격 UUID",
                  dataIndex: "external_order_id_masked",
                  width: 100,
                },
                { title: "마켓", dataIndex: "market_code", width: 90 },
                { title: "상태", dataIndex: "external_status", width: 80 },
                { title: "체결", dataIndex: "executed_quantity", width: 90 },
                { title: "잔여", dataIndex: "remaining_quantity", width: 90 },
                {
                  title: "권고",
                  dataIndex: "recommended_resolution",
                  width: 140,
                  ellipsis: true,
                },
                {
                  title: "Ignore",
                  width: 70,
                  render: (_: unknown, r: Record<string, unknown>) =>
                    r.eligible_for_ignore ? (
                      <Tag color="green">Y</Tag>
                    ) : (
                      <Tag>N</Tag>
                    ),
                },
                {
                  title: "불가 사유",
                  dataIndex: "message",
                  ellipsis: true,
                },
              ]}
            />

            <Space wrap>
              <Button
                loading={dryRunMutation.isPending}
                disabled={selectedConflictIds.length === 0}
                onClick={() => {
                  if (detailUbaId == null) return;
                  dryRunMutation.mutate({
                    ubaId: detailUbaId,
                    conflict_ids: selectedConflictIds,
                    resolution: "IGNORE_WITH_AUDIT",
                    reason: "dry-run ignore validation",
                  });
                }}
              >
                선택 건 Ignore Dry-run
              </Button>
              <Button
                loading={dryRunMutation.isPending}
                disabled={selectedConflictIds.length === 0}
                onClick={() => {
                  if (detailUbaId == null) return;
                  dryRunMutation.mutate({
                    ubaId: detailUbaId,
                    conflict_ids: selectedConflictIds,
                    resolution: "PRESERVE_REMOTE_HISTORY",
                    reason: "dry-run preserve validation",
                  });
                }}
              >
                원격 이력 보존 Dry-run
              </Button>
              <Button
                loading={resumeCheckMutation.isPending}
                onClick={() => {
                  if (detailUbaId == null) return;
                  resumeCheckMutation.mutate(detailUbaId);
                }}
              >
                Resume 사전 점검
              </Button>
              <Button disabled={DRY_RUN_ONLY} type="primary">
                Resume Trading (비활성)
              </Button>
              <Button disabled={DRY_RUN_ONLY}>
                선택 건 Ignore 실행 (비활성)
              </Button>
            </Space>

            {dryRunResult ? (
              <Alert
                type="success"
                showIcon
                title="Dry-run 결과"
                description={
                  <Typography.Paragraph
                    style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}
                  >
                    {JSON.stringify(dryRunResult, null, 2)}
                  </Typography.Paragraph>
                }
              />
            ) : null}

            {resumeCheck ? (
              <Alert
                type={resumeCheck.resumable ? "success" : "warning"}
                showIcon
                title={
                  resumeCheck.resumable
                    ? "Resume 가능"
                    : "Resume 불가 — blockers"
                }
                description={
                  <Typography.Paragraph
                    style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}
                  >
                    {JSON.stringify(resumeCheck, null, 2)}
                  </Typography.Paragraph>
                }
              />
            ) : null}
          </Space>
        ) : null}
      </Drawer>

      <Modal
        title="UPBIT UBA 생성"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        confirmLoading={createMutation.isPending}
        forceRender
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{
            broker_code: "UPBIT",
            account_number: "MAIN",
            apply_recommended_risk: true,
            is_default: true,
          }}
          onFinish={(values) =>
            createMutation.mutate({
              owner_user_id: Number(values.owner_user_id),
              broker_code: "UPBIT",
              account_alias: values.account_alias,
              account_number: values.account_number,
              is_default: Boolean(values.is_default),
              apply_recommended_risk: Boolean(values.apply_recommended_risk),
            })
          }
        >
          <Form.Item
            name="owner_user_id"
            label="owner_user_id"
            rules={[{ required: true }]}
          >
            <InputNumber min={1} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="account_alias" label="별칭">
            <Input placeholder="upbit-main" />
          </Form.Item>
          <Form.Item
            name="account_number"
            label="account_ref (해시 저장)"
            rules={[{ required: true }]}
          >
            <Input placeholder="MAIN" />
          </Form.Item>
          <Form.Item
            name="apply_recommended_risk"
            label="권장 Risk(엔진 필드 포함)"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item name="is_default" label="기본 계좌" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`UBA 수정 #${editTarget ? String(editTarget.user_broker_account_id ?? editTarget.account_id) : ""}`}
        open={editTarget != null}
        onCancel={() => setEditTarget(null)}
        onOk={() => editForm.submit()}
        confirmLoading={updateMutation.isPending}
        forceRender
        afterOpenChange={(opened) => {
          if (!opened || !editTarget) return;
          editForm.setFieldsValue({
            account_alias: String(editTarget.account_name ?? ""),
            is_active: Boolean(editTarget.is_active),
          });
        }}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => {
            if (!editTarget) return;
            const ubaId = Number(
              editTarget.user_broker_account_id ?? editTarget.account_id,
            );
            updateMutation.mutate({
              ubaId,
              body: {
                account_alias: values.account_alias,
                is_active: values.is_active,
              },
            });
          }}
        >
          <Form.Item name="account_alias" label="별칭">
            <Input />
          </Form.Item>
          <Form.Item name="is_active" label="활성" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`Credential ${credTarget ?? ""}`}
        open={credTarget != null}
        onCancel={() => {
          setCredTarget(null);
          credForm.resetFields();
        }}
        onOk={() => credForm.submit()}
        confirmLoading={
          registerCredMutation.isPending || replaceCredMutation.isPending
        }
        forceRender
        destroyOnHidden
      >
        <Form
          form={credForm}
          layout="vertical"
          onFinish={(values) => {
            if (credTarget == null) return;
            const body = {
              access_key: String(values.access_key),
              secret_key: String(values.secret_key),
            };
            const row = rows.find(
              (r) =>
                Number(r.user_broker_account_id ?? r.account_id) ===
                credTarget,
            );
            const registered = Boolean(
              (row?.credential as { registered?: boolean } | undefined)
                ?.registered,
            );
            if (registered) {
              replaceCredMutation.mutate({ ubaId: credTarget, body });
            } else {
              registerCredMutation.mutate({ ubaId: credTarget, body });
            }
          }}
        >
          <Form.Item
            name="access_key"
            label="access_key"
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="off" />
          </Form.Item>
          <Form.Item
            name="secret_key"
            label="secret_key"
            rules={[{ required: true }]}
          >
            <Input.Password autoComplete="off" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
