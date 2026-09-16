/**
 * 운영 상태 색조 — GREEN / YELLOW / RED / GRAY.
 */

export type StatusTone = "green" | "yellow" | "red" | "gray";

export function toneToAntdColor(tone: StatusTone): string {
  switch (tone) {
    case "green":
      return "success";
    case "yellow":
      return "warning";
    case "red":
      return "error";
    default:
      return "default";
  }
}

export function toneFromBoolOnOff(
  on: boolean | null | undefined,
  offIsGray = true,
): StatusTone {
  if (on === true) return "green";
  if (on === false) return offIsGray ? "gray" : "red";
  return "gray";
}

export function toneFromRuntime(state: string | null | undefined): StatusTone {
  const s = String(state ?? "").toUpperCase();
  if (["RUNNING", "HEALTHY", "OK", "CONNECTED", "ACTIVE"].includes(s)) {
    return "green";
  }
  if (
    ["WAITING_SIGNAL", "WARNING", "DEGRADED", "PAUSED", "STALE", "ARM_EXPIRING_SOON"].includes(
      s,
    )
  ) {
    return "yellow";
  }
  if (
    ["ERROR", "CRITICAL", "FAILED", "BLOCKED", "OFFLINE", "KILL"].includes(s)
  ) {
    return "red";
  }
  if (["STOPPED", "OFF", "INACTIVE", "DISABLED", "IDLE"].includes(s)) {
    return "gray";
  }
  return "gray";
}

export function toneFromReadiness(code: string | null | undefined): StatusTone {
  const s = String(code ?? "").toUpperCase();
  if (s === "READY_FOR_AUTO_TRADING" || s === "READY") return "green";
  if (s.includes("WARN") || s.includes("DEGRADED")) return "yellow";
  if (s.includes("BLOCK") || s.includes("FAIL") || s.includes("ERROR")) {
    return "red";
  }
  return "gray";
}
