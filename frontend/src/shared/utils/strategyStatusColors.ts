/**
 * Strategy Request 상태 → Ant Design Tag color (표시 전용).
 * approve/reject/create/cancel action은 포함하지 않음.
 */
export const STRATEGY_REQUEST_STATUS_COLOR: Record<string, string> = {
  PENDING_REVIEW: "processing",
  APPROVED: "success",
  REJECTED: "error",
  CANCELLED: "default",
  EXPIRED: "warning",
};

/**
 * Strategy Draft 상태 → Ant Design Tag color (표시 전용).
 * Draft hub / approval / AI generate action은 포함하지 않음.
 */
export const STRATEGY_DRAFT_STATUS_COLOR: Record<string, string> = {
  DRAFT: "processing",
  REGENERATED: "default",
  SUPERSEDED: "warning",
  ARCHIVED: "error",
};
