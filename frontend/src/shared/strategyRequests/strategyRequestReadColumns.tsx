/**
 * Admin/User Strategy Request 목록 COMMON_READ columns (presentation only).
 * mutation / permission / owner / API fetch / 이력·상세 UI 없음.
 */
import { Tag } from "antd";
import type { ColumnsType } from "antd/es/table";

import { cell } from "@/shared/utils/dataHelpers";
import { STRATEGY_REQUEST_STATUS_COLOR } from "@/shared/utils/strategyStatusColors";

/** shared list column이 읽는 최소 row shape — Admin Record / User StrategyRequestItem 호환 */
export type StrategyRequestReadRow = {
  strategy_request_id?: unknown;
  candidate_id?: unknown;
  status?: unknown;
  requested_at?: unknown;
};

/** M6-C0 SoT — exact common dataIndex 4개 */
export const STRATEGY_REQUEST_READ_COLUMN_KEYS = [
  "strategy_request_id",
  "candidate_id",
  "status",
  "requested_at",
] as const;

export type StrategyRequestReadColumnKey =
  (typeof STRATEGY_REQUEST_READ_COLUMN_KEYS)[number];

/** Admin/User list 기존 라벨 (동일) */
export const STRATEGY_REQUEST_READ_TITLES: Record<
  StrategyRequestReadColumnKey,
  string
> = {
  strategy_request_id: "ID",
  candidate_id: "Candidate",
  status: "상태",
  requested_at: "요청일시",
};

/**
 * Admin list 기존 순서:
 * id → candidate → user_id(Admin-only) → status → lifecycle(Admin-only) → requested_at
 */
export const ADMIN_SR_READ_PREFIX: readonly StrategyRequestReadColumnKey[] = [
  "strategy_request_id",
  "candidate_id",
];
export const ADMIN_SR_READ_AFTER_USER: readonly StrategyRequestReadColumnKey[] =
  ["status"];
export const ADMIN_SR_READ_SUFFIX: readonly StrategyRequestReadColumnKey[] = [
  "requested_at",
];

/** User list = COMMON_READ 전체 순서 */
export const USER_SR_READ_COLUMN_ORDER: readonly StrategyRequestReadColumnKey[] =
  STRATEGY_REQUEST_READ_COLUMN_KEYS;

export type BuildStrategyRequestReadColumnOptions = {
  title?: string;
  width?: number;
};

/** status Tag — M6-A STRATEGY_REQUEST_STATUS_COLOR 재사용 */
export function renderStrategyRequestStatusTag(value: unknown) {
  const code = String(value ?? "");
  return (
    <Tag color={STRATEGY_REQUEST_STATUS_COLOR[code] ?? "default"}>
      {code || cell(value)}
    </Tag>
  );
}

export function createStrategyRequestReadColumn<
  T extends StrategyRequestReadRow = StrategyRequestReadRow,
>(
  key: StrategyRequestReadColumnKey,
  options?: BuildStrategyRequestReadColumnOptions,
): ColumnsType<T>[number] {
  const base = {
    title: options?.title ?? STRATEGY_REQUEST_READ_TITLES[key],
    dataIndex: key,
    key,
    width: options?.width,
  };
  if (key === "status") {
    return {
      ...base,
      render: (value: unknown) => renderStrategyRequestStatusTag(value),
    };
  }
  // requested_at / id / candidate — nullish → "-" (M6-A cell)
  return {
    ...base,
    render: (value: unknown) => cell(value),
  };
}

export function buildStrategyRequestReadColumns<
  T extends StrategyRequestReadRow = StrategyRequestReadRow,
>(
  keys: readonly StrategyRequestReadColumnKey[],
  options?: {
    titles?: Partial<Record<StrategyRequestReadColumnKey, string>>;
    widths?: Partial<Record<StrategyRequestReadColumnKey, number>>;
  },
): ColumnsType<T> {
  return keys.map((key) =>
    createStrategyRequestReadColumn<T>(key, {
      title: options?.titles?.[key],
      width: options?.widths?.[key],
    }),
  );
}
