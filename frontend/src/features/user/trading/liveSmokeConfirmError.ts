/**
 * Guided LIVE Smoke — Confirm 오류 표시 헬퍼.
 * Risk 거절(409) vs DB 오류(500 LIVE_SMOKE_*) 구분.
 */

import { toApiError, type ApiError } from "@/lib/api/apiError";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

const RISK_DETAIL_KO: Record<string, string> = {
  "Projected investment ratio exceeds limit": "투자 비율 한도 초과",
  "Daily loss limit reached": "일일 손실 한도 도달",
  "Projected symbol position exceeds amount limit":
    "종목별 최대 보유금액 초과",
};

function translateRiskDetail(raw: string): string {
  const trimmed = raw.trim();
  if (RISK_DETAIL_KO[trimmed]) return RISK_DETAIL_KO[trimmed];
  const lower = trimmed.toLowerCase();
  if (lower.includes("investment ratio")) return "투자 비율 한도 초과";
  if (lower.includes("daily loss")) return "일일 손실 한도 도달";
  if (lower.includes("symbol position")) return "종목별 최대 보유금액 초과";
  return trimmed;
}

function extractDetailsFromPayload(data: unknown): string[] {
  if (!isRecord(data)) return [];
  const nested = isRecord(data.detail) ? data.detail : data;
  const raw = nested.details;
  if (Array.isArray(raw)) {
    return raw.map((item) => String(item)).filter(Boolean);
  }
  return [];
}

export type ConfirmErrorView = {
  kind: "risk" | "db_error" | "other";
  title: string;
  detailLines: string[];
  orderSubmitted: boolean;
  createOrderCalls: number;
  brokerOrderId: string | null;
  errorCode: string | null;
  status: string | null;
  retryForbidden: boolean;
  /** @deprecated risk 전용 호환 */
  isRiskRejection: boolean;
};

/** @deprecated 이름 유지 — ConfirmErrorView 사용 */
export type RiskRejectionView = ConfirmErrorView;

export function formatLiveSmokeConfirmError(error: unknown): ConfirmErrorView {
  const apiErr: ApiError = toApiError(error);
  const data = apiErr.details;
  const detailRecord = isRecord(data)
    ? isRecord(data.detail)
      ? data.detail
      : data
    : null;

  const code = String(
    apiErr.code ||
      (detailRecord?.error_code as string | undefined) ||
      (detailRecord?.code as string | undefined) ||
      "",
  );
  const details = extractDetailsFromPayload(data);
  const statusLabel =
    detailRecord && typeof detailRecord.status === "string"
      ? detailRecord.status
      : null;

  const isDbError =
    code.startsWith("LIVE_SMOKE_") ||
    apiErr.status === 500 ||
    apiErr.status === 503 ||
    Boolean(detailRecord?.retry_forbidden);

  if (isDbError) {
    return {
      kind: "db_error",
      isRiskRejection: false,
      title: "실주문 요청을 저장하지 못했습니다.",
      detailLines: [
        `상태: ${statusLabel || "FAILED"}`,
        `오류 코드: ${code || "LIVE_SMOKE_DB_ERROR"}`,
        "실제 주문 전송: 없음",
        "Upbit 주문 UUID: 없음",
        "재시도 금지",
        "관리자 로그에서 correlation_id / run_id 확인",
      ],
      orderSubmitted: false,
      createOrderCalls: Number(detailRecord?.create_order_calls ?? 0) || 0,
      brokerOrderId: null,
      errorCode: code || "LIVE_SMOKE_DB_ERROR",
      status: statusLabel || "FAILED",
      retryForbidden: true,
    };
  }

  const isRisk =
    apiErr.status === 409 ||
    apiErr.status === 422 ||
    code.startsWith("RISK_") ||
    details.some((d) => /limit|ratio|loss|position/i.test(d));

  if (!isRisk) {
    return {
      kind: "other",
      isRiskRejection: false,
      title: apiErr.message,
      detailLines: [],
      orderSubmitted: false,
      createOrderCalls: 0,
      brokerOrderId: null,
      errorCode: code || null,
      status: statusLabel,
      retryForbidden: false,
    };
  }

  const detailLines =
    details.length > 0
      ? details.map(translateRiskDetail)
      : [apiErr.message || "Risk policy blocked this order."];

  const orderSubmitted = Boolean(detailRecord?.order_submitted);
  const createOrderCalls = Number(detailRecord?.create_order_calls ?? 0) || 0;
  const brokerRaw = detailRecord?.broker_order_id;
  const brokerOrderId =
    brokerRaw == null || brokerRaw === "" ? null : String(brokerRaw);

  return {
    kind: "risk",
    isRiskRejection: true,
    title: "주문이 Risk 정책에 의해 차단되었습니다.",
    detailLines,
    orderSubmitted,
    createOrderCalls,
    brokerOrderId,
    errorCode: code || "RISK_ENGINE_BLOCKED",
    status: statusLabel || "REJECTED",
    retryForbidden: false,
  };
}
