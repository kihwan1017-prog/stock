"use client";

/**
 * UPBIT one-click autotrading — FE orchestration over existing safety APIs.
 * Backend POST /start|/stop 는 LIVE --reload 위험으로 SAFE_RELOAD_REQUIRED.
 */

import * as adminApi from "@/features/admin/api/adminApi";
import {
  runUpbit24x7StackStart,
  runUpbit24x7StackStop,
  snapshotFromOpsStatus,
  type StackStartOutcome,
} from "@/features/admin/accounts/upbit24x7StackOrchestrator";
import {
  CONFIRM_ENABLE_24H_UNATTENDED,
  CONFIRM_START_EXIT_MONITOR,
  CONFIRM_START_RUNTIME,
  CONFIRM_START_WORKER,
  CONFIRM_STOP_EXIT_MONITOR,
  CONFIRM_STOP_RUNTIME,
  CONFIRM_STOP_WORKER,
} from "@/features/admin/accounts/upbit24x7Confirmations";

export type OneClickOutcome = {
  ok: boolean;
  mode: "START" | "STOP" | "REAUTHORIZE_START";
  reauthorized: boolean;
  stack: StackStartOutcome | null;
  message: string;
};

function newCorrelationId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}`;
}

export async function runUpbitOneClickStart(
  ubaId: number,
  strategyId: number,
): Promise<OneClickOutcome> {
  const ops = await adminApi.getAdminUbaOpsStatus(ubaId, strategyId);
  const snap = snapshotFromOpsStatus(ops);
  let reauthorized = false;

  if (snap.needsReauthorize) {
    await adminApi.reauthorizeAdminUbaUnattended(ubaId, {
      confirmation_text: CONFIRM_ENABLE_24H_UNATTENDED,
      reason: "one_click_autotrading_start",
      horizon_hours: 24,
      correlation_id: newCorrelationId("oneclick"),
      source: "ADMIN_UI",
    });
    reauthorized = true;
  }

  const stack = await runUpbit24x7StackStart({
    fetchOpsStatus: () => adminApi.getAdminUbaOpsStatus(ubaId, strategyId),
    startWorker: (phrase) => adminApi.startAdminLiveOutboxWorker(phrase),
    startExitMonitor: (phrase) => adminApi.startAdminExitMonitor(phrase),
    startRuntime: (phrase) =>
      adminApi.startAdminUbaStrategyRuntime(ubaId, strategyId, phrase),
  });

  return {
    ok: stack.ok,
    mode: reauthorized ? "REAUTHORIZE_START" : "START",
    reauthorized,
    stack,
    message: stack.ok
      ? reauthorized
        ? "24H 재승인 후 자동매매 스택 시작 완료"
        : "자동매매 스택 시작 완료"
      : `시작 실패 @ ${stack.failedStep}: ${stack.failedReason ?? ""}`,
  };
}

export async function runUpbitOneClickStop(
  ubaId: number,
  strategyId: number,
): Promise<OneClickOutcome> {
  const stack = await runUpbit24x7StackStop({
    fetchOpsStatus: () => adminApi.getAdminUbaOpsStatus(ubaId, strategyId),
    stopWorker: (phrase) => adminApi.stopAdminLiveOutboxWorker(phrase),
    stopExitMonitor: (phrase) => adminApi.stopAdminExitMonitor(phrase),
    stopRuntime: (phrase) =>
      adminApi.stopAdminUbaStrategyRuntime(ubaId, strategyId, phrase),
  });

  return {
    ok: stack.ok,
    mode: "STOP",
    reauthorized: false,
    stack,
    message: stack.ok
      ? "자동매매 스택 중지 완료 (LIVE/ARM/24H 유지)"
      : `중지 실패 @ ${stack.failedStep}: ${stack.failedReason ?? ""}`,
  };
}

/** confirmation phrase 상수 노출 (테스트/문서) */
export const ONE_CLICK_PHRASES = {
  CONFIRM_ENABLE_24H_UNATTENDED,
  CONFIRM_START_WORKER,
  CONFIRM_START_EXIT_MONITOR,
  CONFIRM_START_RUNTIME,
} as const;
