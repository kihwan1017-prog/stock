import { describe, expect, it } from "vitest";

import { isRunnerOn } from "./runnerStatus";

describe("STEP45 isRunnerOn", () => {
  it("running 플래그를 우선한다", () => {
    expect(isRunnerOn({ running: true })).toBe(true);
    expect(isRunnerOn({ running: false })).toBe(false);
  });

  it("status 문자열을 인식한다", () => {
    expect(isRunnerOn({ status: "RUNNING" })).toBe(true);
    expect(isRunnerOn({ status: "STOPPED" })).toBe(false);
  });
});
