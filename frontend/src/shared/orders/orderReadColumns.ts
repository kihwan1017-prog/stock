/**
 * Admin/User 주문 목록 COMMON_READ columns (presentation only).
 * mutation / permission / scope filter / API fetch 없음.
 */
import type { ColumnsType } from "antd/es/table";

import { cell } from "@/shared/utils/dataHelpers";
import {
  orderStatusLabelKo,
  sideLabelKo,
} from "@/features/shared/display/tradingDisplayLabelsKo";

/** shared column이 읽는 최소 row shape — Admin Record / User TradeOrder 호환 */
export type OrderReadRow = {
  order_id?: unknown;
  exchange_code?: unknown;
  symbol?: unknown;
  side_code?: unknown;
  status_code?: unknown;
  order_quantity?: unknown;
  order_price?: unknown;
  [key: string]: unknown;
};

/** M6-B0 SoT — exact common dataIndex 7개 */
export const ORDER_READ_COLUMN_KEYS = [
  "order_id",
  "exchange_code",
  "symbol",
  "side_code",
  "status_code",
  "order_quantity",
  "order_price",
] as const;

export type OrderReadColumnKey = (typeof ORDER_READ_COLUMN_KEYS)[number];

/** Admin 주문 목록 표시 라벨 (API dataIndex는 영문 유지) */
export const ADMIN_ORDER_READ_TITLES: Record<OrderReadColumnKey, string> = {
  order_id: "주문번호",
  exchange_code: "시장",
  symbol: "종목",
  side_code: "매수/매도",
  status_code: "상태",
  order_quantity: "수량",
  order_price: "가격",
};

/** User paper/broker 표시 라벨 */
export const USER_ORDER_READ_TITLES: Record<OrderReadColumnKey, string> = {
  order_id: "주문번호",
  exchange_code: "시장",
  symbol: "종목",
  side_code: "구분",
  status_code: "상태",
  order_quantity: "수량",
  order_price: "가격",
};

/**
 * User paper / BrokerOrdersView 기존 표시 순서
 * (Admin과 exchange↔symbol 순서가 다름 — 각 화면이 keys로 조립)
 */
export const USER_ORDER_READ_COLUMN_ORDER: readonly OrderReadColumnKey[] = [
  "order_id",
  "symbol",
  "exchange_code",
  "side_code",
  "status_code",
  "order_quantity",
  "order_price",
];

/** Admin GET /orders 에서 broker 앞·뒤 공통 구간 */
export const ADMIN_ORDER_READ_PREFIX: readonly OrderReadColumnKey[] = ["order_id"];
export const ADMIN_ORDER_READ_SUFFIX: readonly OrderReadColumnKey[] = [
  "exchange_code",
  "symbol",
  "side_code",
  "status_code",
  "order_quantity",
  "order_price",
];

export type BuildOrderReadColumnOptions = {
  title?: string;
  sorter?: boolean;
  width?: number;
};

export function createOrderReadColumn<T extends OrderReadRow = OrderReadRow>(
  key: OrderReadColumnKey,
  options?: BuildOrderReadColumnOptions,
): ColumnsType<T>[number] {
  const base = {
    title: options?.title ?? ADMIN_ORDER_READ_TITLES[key],
    dataIndex: key,
    key,
    width: options?.width,
    sorter: options?.sorter ? true : undefined,
  };
  // 표시만 한글화 — API 원본 code는 그대로 유지
  if (key === "side_code") {
    return {
      ...base,
      render: (value: unknown) => sideLabelKo(value == null ? null : String(value)),
    };
  }
  if (key === "status_code") {
    return {
      ...base,
      render: (value: unknown) =>
        orderStatusLabelKo(value == null ? null : String(value)),
    };
  }
  return {
    ...base,
    render: (value: unknown) => cell(value),
  };
}

export function buildOrderReadColumns<T extends OrderReadRow = OrderReadRow>(
  keys: readonly OrderReadColumnKey[],
  options?: {
    titles?: Partial<Record<OrderReadColumnKey, string>>;
    sorters?: Partial<Record<OrderReadColumnKey, boolean>>;
    widths?: Partial<Record<OrderReadColumnKey, number>>;
  },
): ColumnsType<T> {
  return keys.map((key) =>
    createOrderReadColumn<T>(key, {
      title: options?.titles?.[key],
      sorter: options?.sorters?.[key],
      width: options?.widths?.[key],
    }),
  );
}

/** dataIndex/key 기준으로 특정 READ column만 교체 (User rich status 등) */
export function replaceOrderReadColumn<T extends OrderReadRow = OrderReadRow>(
  columns: ColumnsType<T>,
  key: OrderReadColumnKey,
  next: ColumnsType<T>[number],
): ColumnsType<T> {
  return columns.map((col) => {
    const dataIndex = (col as { dataIndex?: unknown }).dataIndex;
    const colKey = (col as { key?: unknown }).key;
    if (dataIndex === key || colKey === key) {
      return next;
    }
    return col;
  });
}
