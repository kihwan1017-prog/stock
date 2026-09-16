import { describe, expect, it } from "vitest";

import { OPERATION_CENTER_TILES } from "./operationCenterTiles";

describe("STEP51 operation center tiles", () => {
  it("필수 운영 기능을 포함한다", () => {
    const ids = OPERATION_CENTER_TILES.map((tile) => tile.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        "health",
        "scheduler",
        "batch",
        "broker",
        "postgres",
        "monitor",
        "environment",
        "logs",
        "backup",
        "telegram",
        "ollama",
        "restore",
        "runtime",
        "recovery",
        "risk",
        "orders",
      ]),
    );
  });

  it("시스템 모니터링과 거래 운영 현황 타일은 서로 다른 href다", () => {
    const health = OPERATION_CENTER_TILES.find((tile) => tile.id === "health");
    const monitor = OPERATION_CENTER_TILES.find((tile) => tile.id === "monitor");
    expect(health?.href).toBe("/admin/monitoring");
    expect(monitor?.href).toBe("/admin/operations-dashboard");
    expect(health?.href).not.toBe(monitor?.href);
  });
});
