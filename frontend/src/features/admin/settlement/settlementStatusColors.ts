/** STEP 8-9A — 패널과 분리 (Vitest flaky import 완화) */
export const SETTLEMENT_STATUS_COLOR: Record<string, string> = {
  PENDING: "default",
  RUNNING: "blue",
  SUCCEEDED: "green",
  SUCCEEDED_WITH_WARNINGS: "gold",
  RETRY_PENDING: "orange",
  FAILED: "red",
  MANUAL_REVIEW_REQUIRED: "volcano",
  SKIPPED: "purple",
  SUPERSEDED: "default",
};
