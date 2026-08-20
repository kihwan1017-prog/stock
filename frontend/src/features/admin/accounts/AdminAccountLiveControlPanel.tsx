"use client";

/**
 * 계좌 LIVE 제어 — UPBIT + KIWOOM 공통 ACCOUNT LIVE CONTROL.
 * Activation → LIVE ON → ARM ON. Scheduler RUN은 이번 범위에서 비활성.
 */

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
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
  Segmented,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import * as adminApi from "@/features/admin/api/adminApi";
import { AdminDataTable } from "@/features/admin/components/AdminPanels";
import { cell } from "@/features/admin/utils/dataHelpers";
import { adminRoutes } from "@/config/routes";
import { toApiError } from "@/lib/api/apiError";
import { queryKeys } from "@/lib/query/queryKeys";
import Link from "next/link";

import { AccountLiveActivationPanel } from "./AccountLiveActivationPanel";
import {
  findActiveAccountActivation,
  kiwoomExecutionBadges,
  remainingActivationSeconds,
  approvalPhraseForBroker,
} from "./accountLiveActivation";
import {
  runtimeGateBlockers,
  schedulerIsPaused,
  schedulerIsRunning,
  type RuntimeAction,
} from "./accountLiveControlGates";
import {
  LIVE_CONTROL_BROKERS,
  filterRowsByBroker,
  mergeBrokerAccountLists,
  rowBrokerCode,
  rowUbaId,
  type LiveControlBrokerFilter,
} from "./accountLiveControlList";
import { ArmTokenOnceModal } from "./ArmTokenOnceModal";
import {
  parseArmOnSuccessPayload,
  type ArmTokenOnceReveal,
} from "./armTokenOnceReveal";
import { UbaAutoTradingStatusPanel } from "./UbaAutoTradingStatusPanel";
import { buildUbaAutoTradingViewModel } from "./ubaAutoTradingStatus";
import { buildOpsStatusSummary } from "./opsStatusSummary";
import { UnattendedControlCard } from "./UnattendedControlCard";
import { runUpbit24x7StackStart } from "./upbit24x7StackOrchestrator";

function newCorrelationId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Conflict Resolve 실행은 Dry-run 전용 유지 */
const DRY_RUN_ONLY = true;

export function AdminAccountLiveControlPanel() {
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
  const [brokerFilter, setBrokerFilter] =
    useState<LiveControlBrokerFilter>("ALL");
  const [activationUbaId, setActivationUbaId] = useState<number | null>(null);
  const [armReveal, setArmReveal] = useState<ArmTokenOnceReveal | null>(null);
  const [unattendedEnableOpen, setUnattendedEnableOpen] = useState(false);
  const [unattendedEnableBusy, setUnattendedEnableBusy] = useState(false);
  const [createForm] = Form.useForm();
  const [credForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [unattendedEnableForm] = Form.useForm<{
    approval_phrase: string;
    reason: string;
  }>();

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

  const listQueries = useQueries({
    queries: LIVE_CONTROL_BROKERS.map((brokerCode) => ({
      queryKey: ["admin", "broker-accounts", "live-control", brokerCode],
      queryFn: () =>
        adminApi.listAdminBrokerAccounts({
          broker_code: brokerCode,
          include_inactive: true,
          limit: 100,
        }),
    })),
  });
  const listLoading = listQueries.some((q) => q.isLoading);
  const allRows = useMemo(
    () => mergeBrokerAccountLists(listQueries.map((q) => q.data)),
    [listQueries],
  );
  const rows = useMemo(
    () => filterRowsByBroker(allRows, brokerFilter),
    [allRows, brokerFilter],
  );

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

  const detailOpsQuery = useQuery({
    queryKey: ["admin", "uba-ops-status", detailUbaId],
    queryFn: () => adminApi.getAdminUbaOpsStatus(Number(detailUbaId)),
    enabled: detailUbaId != null,
    refetchInterval: 20_000,
  });

  const detailBroker = useMemo(() => {
    if (detailUbaId == null) return null;
    const row = allRows.find((r) => rowUbaId(r) === Number(detailUbaId));
    return row ? rowBrokerCode(row) : null;
  }, [allRows, detailUbaId]);

  const detailUnattendedQuery = useQuery({
    queryKey: ["admin", "uba-unattended", detailUbaId],
    queryFn: () => adminApi.getAdminUbaUnattendedStatus(Number(detailUbaId)),
    enabled: detailUbaId != null && detailBroker === "UPBIT",
    refetchInterval: 20_000,
  });

  // Worker 상태는 readiness.checks.live_outbox_worker로 표시 (중복 호출 최소화)

  const tradingSchedulerQuery = useQuery({
    queryKey: ["admin", "trading-scheduler", "status"],
    queryFn: adminApi.getTradingSchedulerStatus,
    refetchInterval: 15_000,
  });

  const kiwoomConfigQuery = useQuery({
    queryKey: queryKeys.admin.kiwoomConfig(),
    queryFn: adminApi.getKiwoomConfiguration,
  });

  const activationHistoryQuery = useQuery({
    queryKey: queryKeys.admin.liveTransitionHistory(),
    queryFn: adminApi.getLiveTransitionHistory,
    refetchInterval: 15_000,
  });

  const activationActiveQuery = useQuery({
    queryKey: queryKeys.admin.liveTransitionActive(),
    queryFn: adminApi.getLiveTransitionActive,
    refetchInterval: 15_000,
  });

  const preflightQueries = useQueries({
    queries: rows.slice(0, 40).map((row) => {
      const ubaId = rowUbaId(row);
      return {
        queryKey: queryKeys.admin.runtimePreflight(ubaId),
        queryFn: () =>
          adminApi.getRuntimePreflight({
            mode: "LIVE_ON" as const,
            user_broker_account_id: ubaId,
          }),
        enabled: ubaId > 0,
        refetchInterval: 15_000,
      };
    }),
  });

  // UPBIT 행 ops-status (서버 SoT). 과도한 polling 방지.
  const opsStatusQueries = useQueries({
    queries: rows
      .filter((row) => rowBrokerCode(row) === "UPBIT")
      .slice(0, 20)
      .map((row) => {
        const ubaId = rowUbaId(row);
        return {
          queryKey: ["admin", "uba-ops-status", ubaId],
          queryFn: () => adminApi.getAdminUbaOpsStatus(ubaId),
          enabled: ubaId > 0,
          refetchInterval: 20_000,
          staleTime: 15_000,
        };
      }),
  });
  const opsByUbaId = useMemo(() => {
    const map = new Map<number, ReturnType<typeof buildOpsStatusSummary>>();
    for (const q of opsStatusQueries) {
      const data = q.data;
      if (!data || typeof data !== "object") continue;
      const ubaId = Number(
        (data as { user_broker_account_id?: number }).user_broker_account_id,
      );
      if (!Number.isFinite(ubaId) || ubaId <= 0) continue;
      map.set(ubaId, buildOpsStatusSummary(data));
    }
    return map;
  }, [opsStatusQueries]);
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
      queryKey: ["admin", "broker-accounts", "live-control"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "live-ops-readiness"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "trading-scheduler", "status"],
    });
    await queryClient.invalidateQueries({
      queryKey: ["admin", "runtime", "preflight"],
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.admin.liveTransitionHistory(),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.admin.liveTransitionActive(),
    });
    if (detailUbaId != null) {
      await queryClient.invalidateQueries({
        queryKey: ["admin", "broker-accounts", "ops", detailUbaId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["admin", "autotrading-readiness", detailUbaId],
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
    mutationFn: ({
      ubaId,
      brokerCode,
    }: {
      ubaId: number;
      brokerCode: string;
    }) => adminApi.runAdminAccountRecovery(ubaId, brokerCode),
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
      ttl_seconds?: number | null;
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
            ttl_seconds: args.ttl_seconds ?? null,
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
    onSuccess: async (data, vars) => {
      notifySuccess(`${vars.action} 완료 (UBA ${vars.ubaId})`);
      if (vars.action === "ARM_ON") {
        const reveal = parseArmOnSuccessPayload(data, vars.ubaId);
        if (reveal) setArmReveal(reveal);
      }
      await invalidate();
    },
    onError: (err) => notifyError(err),
  });

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

  const preflightByUbaId = useMemo(() => {
    const map = new Map<number, adminApi.RuntimePreflightResponse>();
    rows.slice(0, 40).forEach((row, index) => {
      const ubaId = rowUbaId(row);
      const data = preflightQueries[index]?.data;
      if (ubaId > 0 && data) map.set(ubaId, data);
    });
    return map;
  }, [rows, preflightQueries]);

  const sharedMarketMock =
    String(
      (kiwoomConfigQuery.data as Record<string, unknown> | undefined)
        ?.environment ?? "mock",
    ).toLowerCase() === "mock";

  const activationByUbaId = useMemo(() => {
    const map = new Map<number, Record<string, unknown>>();
    const sources = [activationActiveQuery.data, activationHistoryQuery.data];
    for (const row of allRows) {
      const ubaId = rowUbaId(row);
      const broker = rowBrokerCode(row);
      for (const src of sources) {
        const active = findActiveAccountActivation(src, ubaId, broker);
        if (active) {
          map.set(ubaId, active);
          break;
        }
      }
    }
    return map;
  }, [allRows, activationActiveQuery.data, activationHistoryQuery.data]);

  const isActivationActive = (ubaId: number, brokerCode: string): boolean => {
    if (activationByUbaId.has(ubaId)) return true;
    return (
      findActiveAccountActivation(
        activationActiveQuery.data,
        ubaId,
        brokerCode,
      ) != null
    );
  };

  const preflightLiveOnBlocked = (ubaId: number): boolean => {
    const report = preflightByUbaId.get(ubaId);
    if (!report) return true;
    return !adminApi.isPreflightLiveOnAllowed(report, preflightNowMs);
  };

  const gateContextForRow = (row: Record<string, unknown>) => {
    const ubaId = rowUbaId(row);
    const blocked = preflightLiveOnBlocked(ubaId);
    return {
      schedulerPaused,
      preflightBlocked: blocked,
      activationActive: isActivationActive(ubaId, rowBrokerCode(row)),
      armPreflightBlocked: blocked,
    };
  };

  const confirmRuntimeAction = (
    action: RuntimeAction,
    ubaId: number,
    row: Record<string, unknown>,
  ) => {
    const liveOn = Boolean(row.live_order_enabled);
    const armOn = Boolean(row.live_armed);
    const tradingPaused = Boolean(row.trading_paused);
    const ctx = gateContextForRow(row);
    const ubaPreflight = preflightByUbaId.get(ubaId);
    const ubaFreshness = adminApi.evaluatePreflightFreshness(
      ubaPreflight?.checked_at ?? ubaPreflight?.freshness?.checked_at,
      Number(ubaPreflight?.freshness?.ttl_seconds) ||
        adminApi.PREFLIGHT_TTL_SECONDS,
      preflightNowMs,
    );

    // 실행 순서: Activation ACTIVE → LIVE ON → ARM ON (Scheduler RUN 별도 STEP)
    if (action === "LIVE_ON") {
      if (ctx.preflightBlocked) {
        messageApi.error(
          ubaFreshness.status === "STALE"
            ? "Pre-flight 결과가 STALE(60초 초과)입니다. 재검사 후 LIVE ON 하세요."
            : "Pre-flight Check 가 READY_FOR_LIVE 가 아니라 LIVE ON 불가합니다.",
        );
        return;
      }
      if (!ctx.activationActive) {
        messageApi.error("Activation ACTIVE 후 LIVE ON 가능합니다.");
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
      if (!ctx.activationActive) {
        messageApi.error("Activation ACTIVE 후 ARM ON 가능합니다.");
        return;
      }
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
      messageApi.error(
        "Scheduler RUN은 별도 STEP입니다. 이번 UI에서는 비활성입니다.",
      );
      return;
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
            순서: Activation ACTIVE → LIVE ON → ARM ON (Scheduler RUN 별도 STEP).
            ARM TTL은 잔여 Activation을 초과하지 않습니다.
          </Typography.Text>
        </Space>
      ),
      okText: "실행",
      cancelText: "취소",
      okButtonProps: {
        danger:
          action === "LIVE_ON" || action === "ARM_ON",
      },
      onOk: () => {
        const remaining =
          action === "ARM_ON"
            ? remainingActivationSeconds(activationByUbaId.get(ubaId))
            : null;
        return runtimeControlMutation.mutateAsync({
          action,
          ubaId,
          reason: reasons[action],
          ttl_seconds: remaining,
        });
      },
    });
  };

  const ops = opsQuery.data as Record<string, unknown> | undefined;

  return (
    <Card
      title="계좌 LIVE 제어"
      size="small"
      extra={
        <Space wrap>
          <Segmented
            value={brokerFilter}
            options={[
              { label: "전체", value: "ALL" },
              { label: "UPBIT", value: "UPBIT" },
              { label: "KIWOOM", value: "KIWOOM" },
            ]}
            onChange={(v) =>
              setBrokerFilter(v as LiveControlBrokerFilter)
            }
          />
          <Button
            onClick={() => {
              for (const q of listQueries) void q.refetch();
              void activationHistoryQuery.refetch();
              void activationActiveQuery.refetch();
            }}
          >
            새로고침
          </Button>
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            UPBIT UBA 생성
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="Runtime 제어: Activation ACTIVE → LIVE ON → ARM ON"
        description="Scheduler RUN은 이번 UI expansion에서 비활성입니다. OFF/PAUSE는 Scheduler PAUSE → DISARM → LIVE OFF 순서를 따릅니다."
      />
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        title="UBA-scoped Pre-flight"
        description={
          <Space orientation="vertical" size={4}>
            <Typography.Text>
              각 행은 GET /admin/runtime/preflight?mode=LIVE_ON&amp;user_broker_account_id=&#123;uba&#125; 를 사용합니다.
            </Typography.Text>
            <Link href={adminRoutes.operationsPreflight}>
              전역 Pre-flight Check (운영 메뉴)
            </Link>
          </Space>
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
        (() => {
          const vm = buildUbaAutoTradingViewModel(autotradingReadyQuery.data);
          return (
            <Alert
              type={
                vm.headline === "READY" || vm.headline === "RUNNING"
                  ? "success"
                  : "warning"
              }
              showIcon
              style={{ marginBottom: 12 }}
              title={`AUTO TRADING ${vm.headline} · UBA ${detailUbaId}`}
              description={
                <Space orientation="vertical" size={2}>
                  <Typography.Text type="secondary">
                    상세 Drawer에서 Strategy / Feed / AI / Risk / Readiness 전체 확인
                  </Typography.Text>
                  <Space wrap size={4}>
                    {vm.displayBlockers.slice(0, 6).map((item) => (
                      <Tag key={item} color="red">
                        {item}
                      </Tag>
                    ))}
                  </Space>
                </Space>
              }
            />
          );
        })()
      ) : null}

      <AdminDataTable
        loading={listLoading}
        dataSource={rows}
        rowKey={(row) => String(rowUbaId(row))}
        columns={[
          {
            title: "UBA",
            width: 80,
            render: (_: unknown, row) => cell(rowUbaId(row)),
          },
          {
            title: "Owner",
            dataIndex: "user_id",
            width: 80,
            render: (_: unknown, row) => cell(row.user_id),
          },
          {
            title: "Broker",
            width: 100,
            render: (_: unknown, row) => {
              const broker = rowBrokerCode(row);
              return (
                <Space orientation="vertical" size={2}>
                  <Tag>{broker || "-"}</Tag>
                  {broker === "KIWOOM" ? (
                    <Space size={2} wrap>
                      {(() => {
                        const cred = row.credential as
                          | { verification_status?: string }
                          | undefined;
                        const verified =
                          String(cred?.verification_status ?? "").toUpperCase() ===
                          "VERIFIED";
                        const badges = kiwoomExecutionBadges({
                          credentialVerified: verified,
                          sharedMarketMock,
                        });
                        return (
                          <>
                            <Tag color="blue">
                              Execution: {badges.execution}
                            </Tag>
                            <Tag>
                              Shared Market: {badges.sharedMarket}
                            </Tag>
                          </>
                        );
                      })()}
                    </Space>
                  ) : null}
                </Space>
              );
            },
          },
          {
            title: "Alias",
            dataIndex: "account_name",
            render: (_: unknown, row) => cell(row.account_name),
          },
          {
            title: "Connection",
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
            title: "Credential",
            key: "cred",
            width: 110,
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
            title: "AUTO TRADING",
            key: "auto_trading",
            width: 200,
            render: (_: unknown, row) => {
              const ubaId = rowUbaId(row);
              if (rowBrokerCode(row) !== "UPBIT") {
                return <Typography.Text type="secondary">—</Typography.Text>;
              }
              const ops = opsByUbaId.get(ubaId);
              if (!ops) {
                return (
                  <Space orientation="vertical" size={0}>
                    <Tag>AUTO …</Tag>
                    <Typography.Text style={{ fontSize: 11 }} type="secondary">
                      Unattended · 운영 상세
                    </Typography.Text>
                  </Space>
                );
              }
              return (
                <Tooltip
                  title={
                    <Space orientation="vertical" size={2}>
                      <span>{ops.liveLabel}</span>
                      <span>{ops.armLabel}</span>
                      <span>{ops.activationLabel}</span>
                      <span>{ops.unattendedLabel}</span>
                      <span>
                        {ops.runtimeLabel} · {ops.runnerLabel} ·{" "}
                        {ops.workerLabel} · {ops.exitLabel}
                      </span>
                      <span>{ops.marketLabel}</span>
                      <span>{ops.aiLabel}</span>
                      {ops.primaryBlocker ? (
                        <span>Blocker: {ops.primaryBlocker}</span>
                      ) : (
                        <span>Blocker: NONE</span>
                      )}
                      <span>운영 제어는 「운영 상세」에서</span>
                    </Space>
                  }
                >
                  <Space orientation="vertical" size={0}>
                    <Tag color={ops.color}>{ops.autoTradingState}</Tag>
                    <Typography.Text style={{ fontSize: 11 }}>
                      {ops.liveLabel} · {ops.stackLabel}
                    </Typography.Text>
                    <Typography.Text style={{ fontSize: 11 }} type="secondary">
                      {ops.armLabel} · {ops.activationLabel}
                    </Typography.Text>
                    <Typography.Text style={{ fontSize: 11 }}>
                      {ops.unattendedLabel}
                    </Typography.Text>
                    <Typography.Text style={{ fontSize: 11 }} type="secondary">
                      {ops.workerLabel} · {ops.runtimeLabel}
                    </Typography.Text>
                  </Space>
                </Tooltip>
              );
            },
          },
          {
            title: "Activation",
            key: "activation",
            width: 120,
            render: (_: unknown, row) => {
              const ubaId = rowUbaId(row);
              const active = isActivationActive(ubaId, rowBrokerCode(row));
              return (
                <Space orientation="vertical" size={2}>
                  <Tag color={active ? "green" : "default"}>
                    {active ? "ACTIVE" : "INACTIVE"}
                  </Tag>
                  <Button
                    size="small"
                    onClick={() => setActivationUbaId(ubaId)}
                  >
                    Activation
                  </Button>
                </Space>
              );
            },
          },
          {
            title: "Preflight",
            key: "preflight",
            width: 130,
            render: (_: unknown, row) => {
              const ubaId = rowUbaId(row);
              const report = preflightByUbaId.get(ubaId);
              const allowed = report
                ? adminApi.isPreflightLiveOnAllowed(report, preflightNowMs)
                : false;
              const freshness = adminApi.evaluatePreflightFreshness(
                report?.checked_at ?? report?.freshness?.checked_at,
                Number(report?.freshness?.ttl_seconds) ||
                  adminApi.PREFLIGHT_TTL_SECONDS,
                preflightNowMs,
              );
              return (
                <Space orientation="vertical" size={2}>
                  <Tag color={allowed ? "success" : "warning"}>
                    {String(report?.overall_status ?? "LOADING")}
                  </Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    {freshness.status}
                  </Typography.Text>
                </Space>
              );
            },
          },
          {
            title: "LIVE",
            key: "live_control",
            width: 150,
            render: (_: unknown, row) => {
              const ubaId = rowUbaId(row);
              const liveOn = Boolean(row.live_order_enabled);
              const ctx = gateContextForRow(row);
              const onBlockers = runtimeGateBlockers(
                "LIVE_ON",
                row,
                ctx,
              );
              const offBlockers = runtimeGateBlockers(
                "LIVE_OFF",
                row,
                ctx,
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
              const ubaId = rowUbaId(row);
              const armOn = Boolean(row.live_armed);
              const ctx = gateContextForRow(row);
              const onBlockers = runtimeGateBlockers("ARM_ON", row, ctx);
              const offBlockers = runtimeGateBlockers("ARM_OFF", row, ctx);
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
              const ubaId = rowUbaId(row);
              const ctx = gateContextForRow(row);
              const runBlockers = runtimeGateBlockers(
                "SCHEDULER_RUN",
                row,
                ctx,
              );
              const pauseBlockers = runtimeGateBlockers(
                "SCHEDULER_PAUSE",
                row,
                ctx,
              );
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
                    운영 상세
                  </Button>
                  <Button
                    size="small"
                    loading={retryRecoveryMutation.isPending}
                    onClick={() =>
                      retryRecoveryMutation.mutate({
                        ubaId,
                        brokerCode: rowBrokerCode(row),
                      })
                    }
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
        size={720}
      >
        {opsQuery.isLoading && !ops && autotradingReadyQuery.isLoading ? (
          <Typography.Text>로딩 중…</Typography.Text>
        ) : opsQuery.error && !autotradingReadyQuery.data ? (
          <Alert type="error" title={toApiError(opsQuery.error).message} />
        ) : (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <UbaAutoTradingStatusPanel
              ubaId={Number(detailUbaId)}
              readiness={autotradingReadyQuery.data}
              loading={autotradingReadyQuery.isLoading}
              errorMessage={
                autotradingReadyQuery.error
                  ? toApiError(autotradingReadyQuery.error).message
                  : null
              }
            />

            {detailBroker === "UPBIT" ? (
              (() => {
                const unatt = (detailUnattendedQuery.data ?? {}) as Record<
                  string,
                  unknown
                >;
                const enabled = Boolean(unatt.unattended_enabled);
                const remaining = Number(unatt.remaining_seconds ?? 0);
                const statusCode = String(unatt.status_code ?? "OFF");
                const opsSum = detailOpsQuery.data
                  ? buildOpsStatusSummary(detailOpsQuery.data)
                  : null;
                const startBlockers = (opsSum?.blockers ?? []).filter((b) =>
                  [
                    "KILL_SWITCH_ACTIVE",
                    "LIVE_OFF",
                    "ARM_OFF",
                    "ACTIVATION_INACTIVE",
                  ].includes(b),
                );
                // ops 실패 시에도 버튼은 노출(비활성 아님) — enable API가 gate로 거절
                const startBlocked = startBlockers.length > 0;
                const startReason = startBlocked
                  ? `${startBlockers.join(", ")} — 해소 후 시작 가능`
                  : null;
                return (
                  <Space
                    orientation="vertical"
                    size={8}
                    style={{ width: "100%" }}
                  >
                    {opsSum ? (
                      <Alert
                        type={
                          opsSum.autoTradingState === "RUNNING"
                            ? "success"
                            : opsSum.autoTradingState === "BLOCKED"
                              ? "error"
                              : "info"
                        }
                        showIcon
                        title={`AUTO TRADING ${opsSum.autoTradingState} · ${opsSum.stackLabel}`}
                        description={
                          <Space
                            orientation="vertical"
                            size={2}
                            style={{ width: "100%" }}
                          >
                            <Typography.Text type="secondary">
                              {opsSum.liveLabel} · {opsSum.armLabel} ·{" "}
                              {opsSum.activationLabel} · {opsSum.unattendedLabel}
                            </Typography.Text>
                            <Typography.Text type="secondary">
                              {opsSum.runtimeLabel} · {opsSum.runnerLabel} ·{" "}
                              {opsSum.workerLabel} · {opsSum.exitLabel}
                            </Typography.Text>
                            <Typography.Text type="secondary">
                              {opsSum.marketLabel} · {opsSum.aiLabel}
                              {opsSum.primaryBlocker
                                ? ` · Blocker ${opsSum.primaryBlocker}`
                                : " · Blocker NONE"}
                            </Typography.Text>
                          </Space>
                        }
                      />
                    ) : detailOpsQuery.isError ? (
                      <Alert
                        type="warning"
                        showIcon
                        title="운영 요약(ops-status) 일시 오류"
                        description="Unattended 제어는 아래에서 계속 사용 가능합니다."
                      />
                    ) : null}
                    <UnattendedControlCard
                      enabled={enabled}
                      remainingSeconds={remaining}
                      statusCode={statusCode}
                      startDisabled={Boolean(startBlocked)}
                      startDisabledReason={startReason}
                      loading={detailUnattendedQuery.isFetching}
                      onStart={() => {
                        // destroyOnHidden — Form 연결 전 setFieldsValue 금지
                        setUnattendedEnableOpen(true);
                      }}
                      onStop={() => {
                        modal.confirm({
                          title: "24시간 무인운영 중지",
                          onOk: async () => {
                            try {
                              await adminApi.disableAdminUbaUnattended(
                                Number(detailUbaId),
                                {
                                  confirmation_text: "DISABLE 24H UNATTENDED",
                                  reason: "admin_ui_disable",
                                },
                              );
                              notifySuccess("24H Unattended disabled");
                              await queryClient.invalidateQueries({
                                queryKey: [
                                  "admin",
                                  "uba-unattended",
                                  detailUbaId,
                                ],
                              });
                              await queryClient.invalidateQueries({
                                queryKey: [
                                  "admin",
                                  "uba-ops-status",
                                  detailUbaId,
                                ],
                              });
                            } catch (err) {
                              notifyError(err);
                              throw err;
                            }
                          },
                        });
                      }}
                    />
                  </Space>
                );
              })()
            ) : null}

            {ops ? (
              <>
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
              </>
            ) : null}
          </Space>
        )}
      </Drawer>

      {/* Form이 Modal 밖에 있어야 forceRender 전에도 useForm이 연결됨 */}
      <Form
        form={createForm}
        component={false}
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
        <Modal
          title="UPBIT UBA 생성"
          open={createOpen}
          onCancel={() => setCreateOpen(false)}
          onOk={() => createForm.submit()}
          confirmLoading={createMutation.isPending}
          forceRender
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
        </Modal>
      </Form>

      <Form
        form={editForm}
        component={false}
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
          <Form.Item name="account_alias" label="별칭">
            <Input />
          </Form.Item>
          <Form.Item name="is_active" label="활성" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Modal>
      </Form>

      <Form
        form={credForm}
        component={false}
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
        </Modal>
      </Form>

      <Drawer
        title={`ACCOUNT Activation · UBA ${activationUbaId ?? ""}`}
        open={activationUbaId != null}
        onClose={() => setActivationUbaId(null)}
        size={640}
      >
        {activationUbaId != null ? (() => {
          const row = allRows.find((r) => rowUbaId(r) === activationUbaId);
          if (!row) {
            return (
              <Typography.Text>UBA {activationUbaId} 를 찾을 수 없습니다.</Typography.Text>
            );
          }
          const risk = row.risk as { max_order_amount?: unknown } | undefined;
          return (
            <AccountLiveActivationPanel
              ubaId={activationUbaId}
              brokerCode={rowBrokerCode(row)}
              maxOrderAmount={risk?.max_order_amount}
              notifySuccess={notifySuccess}
              notifyError={notifyError}
            />
          );
        })() : null}
      </Drawer>

      <Modal
        title="24시간 무인운영 시작"
        open={unattendedEnableOpen}
        confirmLoading={unattendedEnableBusy}
        okText="Enable 24H Unattended"
        cancelText="취소"
        destroyOnHidden
        forceRender
        afterOpenChange={(opened) => {
          if (!opened) return;
          unattendedEnableForm.setFieldsValue({
            approval_phrase: "",
            reason: "admin_ui_24h_unattended",
          });
        }}
        onCancel={() => {
          if (unattendedEnableBusy) return;
          setUnattendedEnableOpen(false);
        }}
        onOk={async () => {
          if (detailUbaId == null) return;
          try {
            const values = await unattendedEnableForm.validateFields();
            setUnattendedEnableBusy(true);
            await adminApi.enableAdminUbaUnattended(Number(detailUbaId), {
              confirmation_text: "ENABLE 24H UNATTENDED",
              approval_phrase: values.approval_phrase,
              reason: values.reason || "admin_ui_24h_unattended",
              horizon_hours: 24,
              correlation_id: newCorrelationId("unatt"),
            });
            notifySuccess("24H Unattended enabled");
            setUnattendedEnableOpen(false);
            await queryClient.invalidateQueries({
              queryKey: ["admin", "uba-unattended", detailUbaId],
            });
            await queryClient.invalidateQueries({
              queryKey: ["admin", "uba-ops-status", detailUbaId],
            });
            // lease 성공 후 Worker/Exit/Runtime 스택 기동 제안 (LIVE/ARM은 이미 게이트 통과)
            const readyVm = autotradingReadyQuery.data
              ? buildUbaAutoTradingViewModel(autotradingReadyQuery.data)
              : null;
            const strategyIdNum = Number(readyVm?.strategy.strategyId ?? 0);
            const ubaForStack = Number(detailUbaId);
            if (strategyIdNum > 0) {
              modal.confirm({
                title: "운영 스택도 시작할까요?",
                content:
                  "Unattended lease는 활성화되었습니다. Worker → Exit Monitor → Runtime 순으로 기동합니다. 실패 시 FAIL CLOSED이며 LIVE/ARM safety gate는 우회하지 않습니다.",
                okText: "스택 시작",
                cancelText: "나중에",
                onOk: async () => {
                  const outcome = await runUpbit24x7StackStart({
                    fetchOpsStatus: () =>
                      adminApi.getAdminUbaOpsStatus(ubaForStack, strategyIdNum),
                    startWorker: (phrase) =>
                      adminApi.startAdminLiveOutboxWorker(phrase),
                    startExitMonitor: (phrase) =>
                      adminApi.startAdminExitMonitor(phrase),
                    startRuntime: (phrase) =>
                      adminApi.startAdminUbaStrategyRuntime(
                        ubaForStack,
                        strategyIdNum,
                        phrase,
                      ),
                  });
                  await queryClient.invalidateQueries({
                    queryKey: ["admin", "uba-ops-status", ubaForStack],
                  });
                  await queryClient.invalidateQueries({
                    queryKey: ["admin", "autotrading-readiness", ubaForStack],
                  });
                  if (outcome.ok) {
                    notifySuccess("운영 스택 START 완료");
                  } else {
                    notifyError(
                      new Error(
                        `스택 FAIL @ ${outcome.failedStep}: ${outcome.failedReason ?? ""}`,
                      ),
                    );
                    throw new Error(
                      outcome.failedReason ?? "STACK_START_FAILED",
                    );
                  }
                },
              });
            }
          } catch (err) {
            // form validate 실패는 Ant Design이 처리
            if (err && typeof err === "object" && "errorFields" in err) {
              return;
            }
            notifyError(err);
            throw err;
          } finally {
            setUnattendedEnableBusy(false);
          }
        }}
      >
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title="두 가지 문구가 다릅니다"
          description={
            <Space orientation="vertical" size={4}>
              <Typography.Text>
                confirmation_text (자동 전송):{" "}
                <Typography.Text code>
                  {String(
                    (detailUnattendedQuery.data as Record<string, unknown> | undefined)
                      ?.required_confirmation_text ?? "ENABLE 24H UNATTENDED",
                  )}
                </Typography.Text>
              </Typography.Text>
              <Typography.Text>
                LIVE approval_phrase (아래 입력 · Activation과 동일):{" "}
                <Typography.Text code copyable>
                  {String(
                    (detailUnattendedQuery.data as Record<string, unknown> | undefined)
                      ?.required_approval_phrase ??
                      approvalPhraseForBroker(detailBroker) ??
                      "",
                  )}
                </Typography.Text>
              </Typography.Text>
              <Typography.Text type="secondary">
                confirmation 문구를 approval에 넣으면 INVALID_APPROVAL_PHRASE 입니다.
              </Typography.Text>
            </Space>
          }
        />
        <Form
          form={unattendedEnableForm}
          layout="vertical"
          initialValues={{
            approval_phrase: "",
            reason: "admin_ui_24h_unattended",
          }}
        >
          <Form.Item
            name="approval_phrase"
            label="LIVE approval_phrase"
            extra={
              (() => {
                const required = String(
                  (detailUnattendedQuery.data as Record<string, unknown> | undefined)
                    ?.required_approval_phrase ??
                    approvalPhraseForBroker(detailBroker) ??
                    "",
                );
                return required
                  ? `정확히 입력: ${required}`
                  : "broker별 LIVE 승인 phrase 필요";
              })()
            }
            rules={[{ required: true, message: "LIVE approval phrase 필요" }]}
          >
            <Input
              autoComplete="off"
              placeholder={
                String(
                  (detailUnattendedQuery.data as Record<string, unknown> | undefined)
                    ?.required_approval_phrase ??
                    approvalPhraseForBroker(detailBroker) ??
                    "ENABLE UPBIT LIVE TRADING",
                )
              }
            />
          </Form.Item>
          <Form.Item
            name="reason"
            label="사유"
            rules={[{ required: true, message: "사유 필요" }]}
          >
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <ArmTokenOnceModal
        reveal={armReveal}
        schedulerPaused={schedulerPaused}
        onClose={() => setArmReveal(null)}
      />
    </Card>
  );
}
