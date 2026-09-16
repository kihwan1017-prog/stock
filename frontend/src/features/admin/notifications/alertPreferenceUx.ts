/**
 * Alert Management UX V3 — draft/save helpers (순수 함수).
 * preference_key 가 canonical identity. display_name 을 key 로 쓰지 않음.
 */

export type PrefItem = {
  key: string;
  group: string;
  label: string;
  description: string;
  enabled: boolean;
  updated_at?: string | null;
};

export type SourceFilter = "ALL" | "UPBIT" | "KIWOOM" | "SYSTEM";
export type ImportanceFilter = "ALL" | "IMPORTANT" | "INFO";
export type UxGroupId =
  | "TRADE_FILL"
  | "EXIT_PROTECT"
  | "SAFETY"
  | "OPS"
  | "ANALYSIS";

export type UxMeta = {
  uxGroup: UxGroupId;
  source: "UPBIT" | "KIWOOM" | "SYSTEM";
  importance: "IMPORTANT" | "INFO";
  recommended?: boolean;
  userLabel: string;
  userDescription: string;
};

/** preference_key → 사용자 중심 메타 (DB identity 유지) */
export const PREFERENCE_UX_META: Record<string, UxMeta> = {
  UPBIT_AUTO_BUY: {
    uxGroup: "TRADE_FILL",
    source: "UPBIT",
    importance: "IMPORTANT",
    recommended: true,
    userLabel: "매수 체결",
    userDescription:
      "자동매수 주문이 실제 체결되었을 때 알려줍니다.",
  },
  UPBIT_AUTO_SELL: {
    uxGroup: "EXIT_PROTECT",
    source: "UPBIT",
    importance: "IMPORTANT",
    recommended: true,
    userLabel: "매도·청산 체결",
    userDescription:
      "자동매도/청산 체결 알림입니다. 손절·익절·Trailing·최대보유·MA Dead Cross 등 청산 사유가 포함될 수 있습니다.",
  },
  UPBIT_ORDER_EXCEPTION: {
    uxGroup: "SAFETY",
    source: "UPBIT",
    importance: "IMPORTANT",
    recommended: true,
    userLabel: "주문/체결 이상",
    userDescription: "주문 거부·실패 등 이상 상황을 알려줍니다.",
  },
  UPBIT_RUNTIME: {
    uxGroup: "OPS",
    source: "UPBIT",
    importance: "IMPORTANT",
    userLabel: "자동매매 시작/중지",
    userDescription: "업비트 Runtime 시작·중지·복구를 알려줍니다.",
  },
  KIWOOM_AUTO_BUY: {
    uxGroup: "TRADE_FILL",
    source: "KIWOOM",
    importance: "IMPORTANT",
    recommended: true,
    userLabel: "매수 체결",
    userDescription: "키움 자동매수 체결을 알려줍니다.",
  },
  KIWOOM_AUTO_SELL: {
    uxGroup: "EXIT_PROTECT",
    source: "KIWOOM",
    importance: "IMPORTANT",
    recommended: true,
    userLabel: "매도·청산 체결",
    userDescription: "키움 자동매도/청산 체결을 알려줍니다.",
  },
  KIWOOM_ORDER_EXCEPTION: {
    uxGroup: "SAFETY",
    source: "KIWOOM",
    importance: "IMPORTANT",
    recommended: true,
    userLabel: "주문/체결 이상",
    userDescription: "키움 주문 거부·실패 등을 알려줍니다.",
  },
  KIWOOM_RUNTIME: {
    uxGroup: "OPS",
    source: "KIWOOM",
    importance: "IMPORTANT",
    userLabel: "자동매매 시작/중지",
    userDescription: "키움 Runtime 시작·중지·복구를 알려줍니다.",
  },
  AUTO_LONG_HOLD: {
    uxGroup: "EXIT_PROTECT",
    source: "SYSTEM",
    importance: "IMPORTANT",
    recommended: true,
    userLabel: "장기보유 경고",
    userDescription:
      "설정된 시간 이상 보유 중인 AUTO 포지션을 알려줍니다. 이 알림 자체가 자동매도를 의미하지는 않습니다. (실제 청산 조건인 최대보유시간과 다릅니다.)",
  },
  SYSTEM_OPERATION: {
    uxGroup: "OPS",
    source: "SYSTEM",
    importance: "IMPORTANT",
    recommended: true,
    userLabel: "시스템·일일 리포트",
    userDescription:
      "Kill Switch·복구·시세/런타임 장애·Daily Trading Report 등 운영 알림입니다.",
  },
  UPBIT_AI_DECISION: {
    uxGroup: "ANALYSIS",
    source: "UPBIT",
    importance: "INFO",
    userLabel: "AI 매매 판단 변경",
    userDescription:
      "업비트 AI 매매 판단 상태가 변경되었을 때 알려줍니다. (분석 정보 · 실주문 아님)",
  },
  KIWOOM_AI_DECISION: {
    uxGroup: "ANALYSIS",
    source: "KIWOOM",
    importance: "INFO",
    userLabel: "AI 매매 판단 변경",
    userDescription:
      "키움 AI 매매 판단 상태가 변경되었을 때 알려줍니다. (분석 정보 · 실주문 아님)",
  },
  AUTO_SLOT: {
    uxGroup: "ANALYSIS",
    source: "UPBIT",
    importance: "INFO",
    userLabel: "자동매매 슬롯 등록",
    userDescription:
      "자동매매 슬롯 등록/교체/해제 시 알려줍니다. (분석·운영 정보)",
  },
  CANDIDATE_ANALYSIS: {
    uxGroup: "ANALYSIS",
    source: "UPBIT",
    importance: "INFO",
    userLabel: "시장 후보 분석",
    userDescription:
      "새로운 시장 후보 분석 결과가 만들어졌을 때 알려줍니다.",
  },
  SHADOW_ANALYSIS: {
    uxGroup: "ANALYSIS",
    source: "UPBIT",
    importance: "INFO",
    userLabel: "Shadow 후보 분석",
    userDescription:
      "Shadow 연구/후보 분석 체크포인트 알림입니다. (실주문 아님)",
  },
};

export const UX_GROUP_ORDER: UxGroupId[] = [
  "TRADE_FILL",
  "EXIT_PROTECT",
  "SAFETY",
  "OPS",
  "ANALYSIS",
];

export const UX_GROUP_LABEL: Record<UxGroupId, string> = {
  TRADE_FILL: "거래 체결",
  EXIT_PROTECT: "청산·보호",
  SAFETY: "안전·오류",
  OPS: "운영",
  ANALYSIS: "분석·정보",
};

export const SOURCE_BADGE: Record<string, string> = {
  UPBIT: "업비트",
  KIWOOM: "키움",
  SYSTEM: "시스템",
};

/** 서버 items → enabled map (preference_key) */
export function enabledMapFromItems(
  items: PrefItem[],
): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const item of items) {
    if (!item?.key) continue;
    out[item.key] = Boolean(item.enabled);
  }
  return out;
}

/** draft vs baseline 차이 → PATCH payload */
export function dirtyPreferences(
  draft: Record<string, boolean>,
  baseline: Record<string, boolean>,
): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  const keys = new Set([...Object.keys(draft), ...Object.keys(baseline)]);
  for (const key of keys) {
    if (Boolean(draft[key]) !== Boolean(baseline[key])) {
      out[key] = Boolean(draft[key]);
    }
  }
  return out;
}

export function isDirty(
  draft: Record<string, boolean>,
  baseline: Record<string, boolean>,
): boolean {
  return Object.keys(dirtyPreferences(draft, baseline)).length > 0;
}

/**
 * 연속 토글 후 일괄 저장 시뮬레이션 — 마지막 상태가 그대로 persist payload.
 * save→revert 회귀용.
 */
export function buildBulkSavePayloadAfterToggles(
  initial: Record<string, boolean>,
  toggles: Array<{ key: string; enabled: boolean }>,
): Record<string, boolean> {
  const draft = { ...initial };
  for (const t of toggles) {
    draft[t.key] = t.enabled;
  }
  return dirtyPreferences(draft, initial);
}

export function resolveUxMeta(item: PrefItem): UxMeta {
  const meta = PREFERENCE_UX_META[item.key];
  if (meta) return meta;
  const source =
    item.group === "UPBIT" || item.group === "KIWOOM" || item.group === "SYSTEM"
      ? item.group
      : "SYSTEM";
  return {
    uxGroup: "OPS",
    source,
    importance: "INFO",
    userLabel: item.label || item.key,
    userDescription: item.description || "",
  };
}

export function filterPreferenceItems(
  items: PrefItem[],
  source: SourceFilter,
  importance: ImportanceFilter,
): PrefItem[] {
  return items.filter((item) => {
    const meta = resolveUxMeta(item);
    if (source !== "ALL" && meta.source !== source) return false;
    if (importance !== "ALL" && meta.importance !== importance) return false;
    return true;
  });
}

export function groupItemsByUx(
  items: PrefItem[],
): Record<UxGroupId, PrefItem[]> {
  const out: Record<UxGroupId, PrefItem[]> = {
    TRADE_FILL: [],
    EXIT_PROTECT: [],
    SAFETY: [],
    OPS: [],
    ANALYSIS: [],
  };
  for (const item of items) {
    const meta = resolveUxMeta(item);
    out[meta.uxGroup].push(item);
  }
  return out;
}

/** 사용자 요청 5개 알림 intent → preference_key (SYSTEM/UPBIT AI 는 동일 key) */
export const USER_REQUESTED_DISABLE = [
  {
    intent: "SYSTEM_AI_TRADING_DECISION",
    preference_key: "UPBIT_AI_DECISION",
    event_type: "AI_GATE_RECOMMENDATION_CHANGED",
    note: "Telegram [시스템] 표기 · preference UPBIT_AI_DECISION",
  },
  {
    intent: "UPBIT_MARKET_CANDIDATE_ANALYSIS",
    preference_key: "CANDIDATE_ANALYSIS",
    event_type: "UPBIT_SCANNER_CANDIDATE",
  },
  {
    intent: "UPBIT_AUTO_SLOT_REGISTERED",
    preference_key: "AUTO_SLOT",
    event_type: "UPBIT_PORTFOLIO_SLOT_ASSIGNED",
  },
  {
    intent: "UPBIT_AI_TRADING_DECISION",
    preference_key: "UPBIT_AI_DECISION",
    event_type: "AI_GATE_RECOMMENDATION_CHANGED",
    note: "SYSTEM intent 와 동일 preference_key (canonical 1건)",
  },
  {
    intent: "UPBIT_SHADOW_CANDIDATE_ANALYSIS",
    preference_key: "SHADOW_ANALYSIS",
    event_type: "UPBIT_SCANNER_SHADOW_OPENED",
  },
] as const;

export const UNIQUE_DISABLE_KEYS = [
  "UPBIT_AI_DECISION",
  "CANDIDATE_ANALYSIS",
  "AUTO_SLOT",
  "SHADOW_ANALYSIS",
] as const;
