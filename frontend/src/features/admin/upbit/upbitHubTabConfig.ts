/** M5-A: /admin/upbit 내부 Tab shell 키·라벨 (route/query 없음) */

export const UPBIT_HUB_TAB_KEYS = {
  overview: "overview",
  technical: "technical",
  news: "news",
  ab: "ab",
  ops: "ops",
} as const;

export type UpbitHubTabKey =
  (typeof UPBIT_HUB_TAB_KEYS)[keyof typeof UPBIT_HUB_TAB_KEYS];

/** 업무 흐름 순서: Technical → News → A/B → Ops (N6가 N2–N5보다 앞이면 안 됨) */
export const UPBIT_HUB_TAB_ORDER: readonly UpbitHubTabKey[] = [
  UPBIT_HUB_TAB_KEYS.overview,
  UPBIT_HUB_TAB_KEYS.technical,
  UPBIT_HUB_TAB_KEYS.news,
  UPBIT_HUB_TAB_KEYS.ab,
  UPBIT_HUB_TAB_KEYS.ops,
] as const;

/**
 * 라벨: M5-0 권장.
 * Technical은 메뉴의「기술지표 관리」와 도메인이 달라 억지 한글화하지 않음.
 */
export const UPBIT_HUB_TAB_LABELS: Record<UpbitHubTabKey, string> = {
  overview: "개요",
  technical: "Technical",
  news: "뉴스 파이프라인",
  ab: "A/B 실험",
  ops: "운영·정합",
};
