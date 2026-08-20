/**
 * Ops-status SoT → 표 셀 / Drawer 요약 (AUTO TRADING 컬럼).
 * FE에서 RUNNING을 추정하지 않고 서버 auto_trading_state를 우선한다.
 */

export type OpsStatusSummary = {
  autoTradingState: string;
  liveLabel: string;
  armLabel: string;
  activationLabel: string;
  unattendedLabel: string;
  runtimeLabel: string;
  runnerLabel: string;
  workerLabel: string;
  exitLabel: string;
  stackLabel: string;
  marketLabel: string;
  aiLabel: string;
  primaryBlocker: string | null;
  blockers: string[];
  color: string;
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stateColor(state: string): string {
  switch (state) {
    case "RUNNING":
      return "success";
    case "WAITING_SIGNAL":
      return "processing";
    case "BLOCKED":
      return "error";
    case "DEGRADED":
      return "warning";
    default:
      return "default";
  }
}

export function buildOpsStatusSummary(payload: unknown): OpsStatusSummary {
  const root = asRecord(payload);
  const state = String(root.auto_trading_state ?? "STOPPED").toUpperCase();
  const stack = asRecord(root.runtime_stack);
  const unattended = asRecord(root.unattended);
  const market = asRecord(root.market_feed);
  const armOn = String(root.arm ?? "OFF").toUpperCase() === "ON";
  const liveOn = String(root.live ?? "OFF").toUpperCase() === "ON";
  const unattOn = Boolean(unattended.unattended_enabled);
  const remUnatt = Number(unattended.remaining_seconds ?? 0);
  const remLabel =
    remUnatt > 0
      ? `${Math.floor(remUnatt / 3600)}h ${Math.floor((remUnatt % 3600) / 60)}m`
      : "—";

  const runtime = String(root.runtime ?? stack.runtime ?? "STOPPED").toUpperCase();
  const runner = String(root.runner ?? stack.runner ?? "STOPPED").toUpperCase();
  const worker = String(
    root.outbox_worker ?? stack.outbox_worker ?? "STOPPED",
  ).toUpperCase();
  const exit = String(
    root.exit_monitor ?? stack.exit_monitor ?? "STOPPED",
  ).toUpperCase();

  return {
    autoTradingState: state,
    liveLabel: liveOn ? "LIVE ON" : "LIVE OFF",
    armLabel: armOn
      ? `ARM ${String(root.arm_remaining_label ?? "ON")}`
      : "ARM OFF",
    activationLabel: `ACT ${String(root.activation_remaining_label ?? root.activation ?? "-")}`,
    unattendedLabel: unattOn ? `24H ON · ${remLabel}` : "24H OFF",
    runtimeLabel: `RT ${runtime}`,
    runnerLabel: `RN ${runner}`,
    workerLabel: `WK ${worker}`,
    exitLabel: `EX ${exit}`,
    stackLabel: String(stack.label ?? "0/4"),
    marketLabel: String(market.status ?? "UNKNOWN"),
    aiLabel: `AI ${String(root.ai_state ?? "HOLD")}`,
    primaryBlocker:
      root.primary_blocker != null ? String(root.primary_blocker) : null,
    blockers: Array.isArray(root.blockers)
      ? root.blockers.map((x) => String(x))
      : [],
    color: stateColor(state),
  };
}
