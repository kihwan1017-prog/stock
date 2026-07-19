/** STEP45 — realtime runner status가 ON인지 판별 */
export function isRunnerOn(data: unknown): boolean {
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    return false;
  }
  const row = data as Record<string, unknown>;
  if (typeof row.running === "boolean") return row.running;
  if (typeof row.is_running === "boolean") return row.is_running;
  if (typeof row.active === "boolean") return row.active;
  const status = String(row.status ?? row.state ?? "").toUpperCase();
  return ["RUNNING", "STARTED", "ACTIVE", "ON"].includes(status);
}
