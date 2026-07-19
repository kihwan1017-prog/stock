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
        "restore",
      ]),
    );
  });
});
