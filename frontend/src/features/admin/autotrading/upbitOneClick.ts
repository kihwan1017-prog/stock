"use client";

/**
 * UPBIT one-click — Backend canonical orchestrator 단일 호출.
 * FE multi-call reauthorize→stack 제거.
 */

import * as adminApi from "@/features/admin/api/adminApi";
import { asRecord } from "@/shared/utils/dataHelpers";

export type OrchestratorStep = {
  name: string;
  status: string;
  message_ko?: string | null;
  detail?: Record<string, unknown>;
};

export type OneClickOutcome = {
  ok: boolean;
  mode: "START" | "STOP" | "REAUTHORIZE_START" | "STOP_FULL";
  reauthorized: boolean;
  status: string;
  steps: OrchestratorStep[];
  failedStep: string | null;
  reasonCode: string | null;
  message: string;
  readiness: string | null;
  raw: Record<string, unknown>;
};

function parseOutcome(
  raw: unknown,
  mode: OneClickOutcome["mode"],
  reauthorized: boolean,
): OneClickOutcome {
  const r = asRecord(raw) ?? {};
  const status = String(r.status ?? "");
  const ok =
    status === "READY" ||
    status === "ALREADY_RUNNING" ||
    status === "STOPPED";
  const stepsRaw = Array.isArray(r.steps) ? r.steps : [];
  const steps: OrchestratorStep[] = stepsRaw.map((s) => {
    const row = asRecord(s) ?? {};
    return {
      name: String(row.name ?? ""),
      status: String(row.status ?? ""),
      message_ko:
        row.message_ko == null ? null : String(row.message_ko),
      detail: asRecord(row.detail) ?? undefined,
    };
  });
  const failedStep =
    r.failed_step == null ? null : String(r.failed_step);
  const reasonCode =
    r.reason_code == null ? null : String(r.reason_code);
  const readiness =
    r.readiness == null ? null : String(r.readiness);
  let message = "";
  if (ok && mode.startsWith("STOP")) {
    message =
      mode === "STOP_FULL"
        ? "완전 종료(스택) 완료 — LIVE/ARM은 계좌 화면에서 별도"
        : "신규 매수 중지 · 기존 포지션 보호(Exit) 유지";
  } else if (ok) {
    message =
      status === "ALREADY_RUNNING"
        ? "이미 자동매매 가동 중"
        : reauthorized
          ? "24H 재승인 후 자동매매 준비 완료"
          : "자동매매 준비 완료";
  } else {
    message = `실패 @ ${failedStep ?? "?"}: ${reasonCode ?? ""}`;
  }
  return {
    ok,
    mode,
    reauthorized,
    status,
    steps,
    failedStep,
    reasonCode,
    message,
    readiness,
    raw: r,
  };
}

export async function runUpbitOneClickStart(
  ubaId: number,
  strategyId: number,
  options?: { reauthorizeUnattended?: boolean },
): Promise<OneClickOutcome> {
  const reauth = Boolean(options?.reauthorizeUnattended);
  const raw = await adminApi.startAdminUbaAutotrading(ubaId, {
    reauthorize_unattended: reauth,
    strategy_id: strategyId,
    correlation_id: `fe-oneclick-${Date.now().toString(36)}`,
  });
  return parseOutcome(
    raw,
    reauth ? "REAUTHORIZE_START" : "START",
    reauth,
  );
}

export async function runUpbitOneClickStop(
  ubaId: number,
  strategyId: number,
  options?: { mode?: "ENTRY_ONLY" | "FULL" },
): Promise<OneClickOutcome> {
  const mode = options?.mode ?? "ENTRY_ONLY";
  const raw = await adminApi.stopAdminUbaAutotrading(ubaId, {
    mode,
    strategy_id: strategyId,
  });
  return parseOutcome(
    raw,
    mode === "FULL" ? "STOP_FULL" : "STOP",
    false,
  );
}

/** @deprecated 개별 confirm phrase는 backend orchestrator 내부에서만 사용 */
export const ONE_CLICK_PHRASES = {
  NOTE: "canonical_backend_orchestrator",
} as const;
