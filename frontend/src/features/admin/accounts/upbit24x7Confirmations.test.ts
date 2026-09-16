import { describe, expect, it } from "vitest";

import {
  APPROVAL_ENABLE_UPBIT_LIVE,
  CONFIRM_ENABLE_24H_UNATTENDED,
  CONFIRM_START_EXIT_MONITOR,
  CONFIRM_START_RUNTIME,
  CONFIRM_START_WORKER,
  CONFIRM_STOP_EXIT_MONITOR,
  CONFIRM_STOP_RUNTIME,
  CONFIRM_STOP_WORKER,
} from "./upbit24x7Confirmations";

describe("upbit24x7Confirmations", () => {
  it("matches backend upbit_24x7_control phrases", () => {
    expect(CONFIRM_START_RUNTIME).toBe("START RUNTIME");
    expect(CONFIRM_STOP_RUNTIME).toBe("STOP RUNTIME");
    expect(CONFIRM_START_WORKER).toBe("START OUTBOX WORKER");
    expect(CONFIRM_STOP_WORKER).toBe("STOP OUTBOX WORKER");
    expect(CONFIRM_START_EXIT_MONITOR).toBe("START EXIT MONITOR");
    expect(CONFIRM_STOP_EXIT_MONITOR).toBe("STOP EXIT MONITOR");
  });

  it("keeps strong-approval phrases distinct", () => {
    expect(CONFIRM_ENABLE_24H_UNATTENDED).toBe("ENABLE 24H UNATTENDED");
    expect(APPROVAL_ENABLE_UPBIT_LIVE).toBe("ENABLE UPBIT LIVE TRADING");
    expect(CONFIRM_ENABLE_24H_UNATTENDED).not.toBe(APPROVAL_ENABLE_UPBIT_LIVE);
  });
});
