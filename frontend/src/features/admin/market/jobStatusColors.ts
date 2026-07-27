/** STEP 8-9A — 패널과 분리 (Vitest flaky import 완화) */
export const JOB_STATUS_COLOR: Record<string, string> = {
  SCHEDULED: "default",
  CLAIMED: "gold",
  RUNNING: "blue",
  SUCCEEDED: "green",
  FAILED: "red",
  RETRY_PENDING: "orange",
  SKIPPED: "purple",
  SUPERSEDED: "default",
  CANCELLED: "default",
  EXPIRED: "volcano",
};
