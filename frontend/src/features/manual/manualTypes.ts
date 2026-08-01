/** 통합 사용 매뉴얼 — 공통 타입 */

export type ManualStatus =
  | "available"
  | "conditional"
  | "admin_approval"
  | "default_off"
  | "shadow_dry_run"
  | "limited"
  | "unimplemented"
  | "planned";

export interface ManualSection {
  id: string;
  title: string;
  menuPath?: string;
  route?: string;
  status?: ManualStatus;
  purpose: string;
  prerequisites?: string[];
  steps: string[];
  buttons?: string[];
  normalState?: string[];
  errors?: string[];
  liveImpact: string;
  nextSteps?: string[];
  notes?: string[];
}

export interface ManualGuideStep {
  id: string;
  title: string;
  detail: string;
  status?: ManualStatus;
}

export interface ManualMarketFlow {
  id: string;
  title: string;
  status: ManualStatus;
  steps: string[];
  warnings: string[];
}

export const MANUAL_STATUS_LABEL: Record<ManualStatus, string> = {
  available: "사용 가능",
  conditional: "조건부 가능",
  admin_approval: "관리자 승인 필요",
  default_off: "기본 OFF",
  shadow_dry_run: "Shadow/Dry-run",
  limited: "제한됨",
  unimplemented: "미구현",
  planned: "계획됨",
};

export const MANUAL_STATUS_COLOR: Record<ManualStatus, string> = {
  available: "success",
  conditional: "processing",
  admin_approval: "warning",
  default_off: "default",
  shadow_dry_run: "cyan",
  limited: "orange",
  unimplemented: "error",
  planned: "purple",
};
