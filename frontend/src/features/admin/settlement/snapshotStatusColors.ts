/** STEP 8-9A — 패널과 분리해 Vitest가 antd 전체 로드를 피하도록 함 */
export const SNAPSHOT_STATUS_COLOR: Record<string, string> = {
  ACTIVE: "green",
  ORPHAN: "volcano",
  STALE: "orange",
  SUPERSEDED: "default",
  INVALID: "red",
  REBIND_PENDING: "gold",
  REBOUND: "cyan",
  RETIRED: "default",
  PURGED: "default",
};
