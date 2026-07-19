import { describe, expect, it } from "vitest";

import {
  NOTIFICATION_EVENT_CATALOG,
  TELEGRAM_OPS_COMMAND_CATALOG,
} from "./opsCatalog";

describe("STEP54 ops catalogs", () => {
  it("필수 알림 이벤트를 포함한다", () => {
    const ids = NOTIFICATION_EVENT_CATALOG.map((item) => item.id);
    expect(ids).toEqual(
      expect.arrayContaining([
        "SYSTEM_START",
        "SYSTEM_STOP",
        "ORDER_SUBMITTED",
        "ORDER_FILLED",
        "ORDER_REJECTED",
        "STOP_LOSS",
        "TAKE_PROFIT",
        "TRAILING_STOP",
        "RELATIVE_LOSS",
        "KILL_SWITCH",
        "DAILY_LOSS",
        "AI_ANALYSIS_COMPLETE",
        "BACKTEST_COMPLETE",
        "BROKER_DISCONNECTED",
        "BROKER_RECONNECTED",
        "DATABASE_ERROR",
        "SCHEDULER_ERROR",
      ]),
    );
  });

  it("필수 Telegram 명령을 포함한다", () => {
    const commands = TELEGRAM_OPS_COMMAND_CATALOG.map((item) => item.command);
    expect(commands).toEqual([
      "/status",
      "/system",
      "/health",
      "/orders",
      "/positions",
      "/kill",
      "/resume",
      "/help",
    ]);
  });
});
