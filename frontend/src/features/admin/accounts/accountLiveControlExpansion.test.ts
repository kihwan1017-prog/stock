import { describe, expect, it } from "vitest";

import {
  APPROVAL_PHRASE_BY_BROKER,
  buildAccountActivationApprovePayload,
  buildAccountActivationPayload,
  buildAccountActivationRequestPayload,
  DEFAULT_ACTIVATION_TTL_HOURS,
  findActiveAccountActivation,
  isAccountActivationActiveForUba,
  isValidateReady,
  LIVE_TRANSITION_ACCOUNT_SCOPE,
  remainingActivationSeconds,
} from "./accountLiveActivation";
import {
  buildArmPreflightParams,
  buildRuntimePreflightParams,
  runtimeGateBlockers,
  SCHEDULER_RUN_DISABLED_REASON,
} from "./accountLiveControlGates";
import {
  filterRowsByBroker,
  hasUba,
  mergeBrokerAccountLists,
  rowBrokerCode,
  rowUbaId,
} from "./accountLiveControlList";

describe("accountLiveActivation", () => {
  it("G — KIWOOM 1381 validate payload ACCOUNT scope", () => {
    const body = buildAccountActivationPayload({
      brokerCode: "KIWOOM",
      userBrokerAccountId: 1381,
    });
    expect(body).toEqual({
      max_order_amount: 5000,
      max_daily_loss: 5000,
      paper_validation_approved: false,
      scope: "ACCOUNT",
      broker_code: "KIWOOM",
      user_broker_account_id: 1381,
    });
  });

  it("H — request payload includes requested_by", () => {
    const body = buildAccountActivationRequestPayload({
      brokerCode: "UPBIT",
      userBrokerAccountId: 1380,
      requestedBy: "admin",
    });
    expect(body?.requested_by).toBe("admin");
    expect(body?.scope).toBe(LIVE_TRANSITION_ACCOUNT_SCOPE);
  });

  it("I/J/K — approve phrase + ttl + no BROKER scope", () => {
    const body = buildAccountActivationApprovePayload({
      brokerCode: "KIWOOM",
      userBrokerAccountId: 1381,
      approvedBy: "admin",
      approvalPhrase: APPROVAL_PHRASE_BY_BROKER.KIWOOM,
    });
    expect(body?.approval_phrase).toBe("ENABLE KIWOOM LIVE TRADING");
    expect(body?.ttl_hours).toBe(DEFAULT_ACTIVATION_TTL_HOURS);
    expect(body?.scope).toBe("ACCOUNT");
    expect(
      buildAccountActivationPayload({
        brokerCode: "KIWOOM",
        userBrokerAccountId: 1381,
      })?.scope,
    ).not.toBe("BROKER");
  });

  it("remainingActivationSeconds prefers remaining_ttl then expires_at", () => {
    const nowMs = Date.parse("2026-08-18T12:00:00.000Z");
    expect(
      remainingActivationSeconds(
        { remaining_ttl_seconds: 1800 },
        nowMs,
      ),
    ).toBe(1800);
    expect(
      remainingActivationSeconds(
        { expires_at: "2026-08-18T12:30:00.000Z" },
        nowMs,
      ),
    ).toBe(1800);
    expect(
      remainingActivationSeconds(
        { expires_at: "2026-08-18T11:59:00.000Z" },
        nowMs,
      ),
    ).toBeNull();
    expect(remainingActivationSeconds(null, nowMs)).toBeNull();
  });

  it("detects ACTIVE ACCOUNT activation for UBA", () => {
    const item = {
      enabled: true,
      scope: "ACCOUNT",
      broker_code: "KIWOOM",
      user_broker_account_id: 1381,
      activation_status: "ACTIVE",
    };
    expect(isAccountActivationActiveForUba(item, 1381, "KIWOOM")).toBe(true);
    expect(findActiveAccountActivation({ items: [item] }, 1381, "KIWOOM")).not.toBeNull();
  });

  it("isValidateReady reads backend ready flag", () => {
    expect(isValidateReady({ ready: true })).toBe(true);
    expect(isValidateReady({ ready: false })).toBe(false);
  });
});

describe("accountLiveControlGates", () => {
  const readyRow = {
    live_order_enabled: false,
    live_armed: false,
    trading_paused: false,
    connection_status: "CONNECTED",
    recovery_status: "SUCCESS",
    active_conflict_count: 0,
    credential: { registered: true, verification_status: "VERIFIED" },
  };

  const ctxReady = {
    schedulerPaused: true,
    preflightBlocked: false,
    activationActive: true,
  };

  it("L — Activation inactive disables LIVE", () => {
    const blockers = runtimeGateBlockers("LIVE_ON", readyRow, {
      ...ctxReady,
      activationActive: false,
    });
    expect(blockers.some((b) => b.includes("Activation ACTIVE"))).toBe(true);
  });

  it("M — Activation active + READY enables LIVE (no blockers)", () => {
    expect(runtimeGateBlockers("LIVE_ON", readyRow, ctxReady)).toEqual([]);
  });

  it("N — LIVE OFF disables ARM", () => {
    expect(
      runtimeGateBlockers("ARM_ON", readyRow, ctxReady).some((b) =>
        b.includes("LIVE OFF"),
      ),
    ).toBe(true);
  });

  it("O — LIVE ON enables ARM when gates pass", () => {
    const blockers = runtimeGateBlockers(
      "ARM_ON",
      { ...readyRow, live_order_enabled: true },
      ctxReady,
    );
    expect(blockers).toEqual([]);
  });

  it("P — Scheduler PAUSE required for LIVE", () => {
    expect(
      runtimeGateBlockers("LIVE_ON", readyRow, {
        ...ctxReady,
        schedulerPaused: false,
      }).some((b) => b.includes("Scheduler")),
    ).toBe(true);
  });

  it("Q — paused=true disabled", () => {
    expect(
      runtimeGateBlockers("LIVE_ON", { ...readyRow, trading_paused: true }, ctxReady).some(
        (b) => b.includes("일시중지"),
      ),
    ).toBe(true);
  });

  it("R — recovery FAILED disabled", () => {
    expect(
      runtimeGateBlockers(
        "LIVE_ON",
        { ...readyRow, recovery_status: "FAILED" },
        ctxReady,
      ).some((b) => b.includes("Recovery failed")),
    ).toBe(true);
  });

  it("S — credential missing disabled", () => {
    expect(
      runtimeGateBlockers(
        "LIVE_ON",
        { ...readyRow, credential: { registered: false } },
        ctxReady,
      ).some((b) => b.includes("Credential required")),
    ).toBe(true);
  });

  it("Scheduler RUN always disabled in this STEP", () => {
    expect(runtimeGateBlockers("SCHEDULER_RUN", readyRow, ctxReady)).toEqual([
      SCHEDULER_RUN_DISABLED_REASON,
    ]);
  });

  it("E/F — UBA-scoped preflight params", () => {
    expect(buildRuntimePreflightParams(1381)).toEqual({
      mode: "LIVE_ON",
      user_broker_account_id: 1381,
    });
    expect(buildArmPreflightParams(1380)).toEqual({
      mode: "ARM_ON",
      user_broker_account_id: 1380,
    });
  });
});

describe("accountLiveControlList", () => {
  it("B/C/D — merges UPBIT 1380 + KIWOOM 1381 + other Kiwoom", () => {
    const merged = mergeBrokerAccountLists([
      { items: [{ user_broker_account_id: 1380, broker_code: "UPBIT" }] },
      {
        items: [
          { user_broker_account_id: 1381, broker_code: "KIWOOM" },
          { user_broker_account_id: 999, broker_code: "KIWOOM" },
        ],
      },
    ]);
    expect(hasUba(merged, 1380)).toBe(true);
    expect(hasUba(merged, 1381)).toBe(true);
    expect(hasUba(merged, 999)).toBe(true);
    expect(merged.map((r) => rowUbaId(r)).sort((a, b) => a - b)).toEqual([
      999, 1380, 1381,
    ]);
  });

  it("broker filter", () => {
    const rows = mergeBrokerAccountLists([
      { items: [{ user_broker_account_id: 1380, broker_code: "UPBIT" }] },
      { items: [{ user_broker_account_id: 1381, broker_code: "KIWOOM" }] },
    ]);
    expect(filterRowsByBroker(rows, "KIWOOM")).toHaveLength(1);
    expect(filterRowsByBroker(rows, "ALL")).toHaveLength(2);
  });
});

describe("adminApi live-transition wrappers", () => {
  it("10–12 — exports validate/request/approve/active", async () => {
    const mod = await import("@/features/admin/api/adminApi");
    expect(typeof mod.validateLiveTransition).toBe("function");
    expect(typeof mod.requestLiveTransition).toBe("function");
    expect(typeof mod.approveLiveTransition).toBe("function");
    expect(typeof mod.getLiveTransitionActive).toBe("function");
    expect(typeof mod.getRuntimePreflight).toBe("function");
  });

  it("getRuntimePreflight accepts user_broker_account_id", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(
      join(process.cwd(), "src/features/admin/api/adminApi.ts"),
      "utf8",
    );
    expect(src).toMatch(/user_broker_account_id\?: number/);
  });
});

describe("AdminAccountLiveControlPanel surface", () => {
  it("A — panel title and KIWOOM list + UBA preflight + no BROKER scope UI", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const panel = readFileSync(
      join(process.cwd(), "src/features/admin/accounts/AdminAccountLiveControlPanel.tsx"),
      "utf8",
    );
    const activation = readFileSync(
      join(process.cwd(), "src/features/admin/accounts/AccountLiveActivationPanel.tsx"),
      "utf8",
    );
    expect(panel).toMatch(/title="계좌 LIVE 제어"/);
    expect(panel).not.toMatch(/UPBIT LIVE UBA \(STEP 8-9C\)/);
    expect(panel).toMatch(/LIVE_CONTROL_BROKERS/);
    expect(panel).toMatch(/listAdminBrokerAccounts/);
    expect(panel).toMatch(/user_broker_account_id: ubaId/);
    expect(panel).toMatch(/AccountLiveActivationPanel/);
    expect(activation).toMatch(/validateLiveTransition/);
    expect(activation).toMatch(/requestLiveTransition/);
    expect(activation).toMatch(/approveLiveTransition/);
    expect(activation).toMatch(/scope=ACCOUNT/);
    expect(activation).not.toMatch(/scope:\s*"BROKER"/);
    expect(panel).toMatch(/setAdminLiveOrderEnabled/);
    expect(panel).toMatch(/armAdminLiveOrder/);
    expect(panel).toMatch(/disarmAdminLiveOrder/);
    expect(panel).toMatch(/Scheduler RUN은 별도 STEP/);
    expect(panel).toMatch(/ArmTokenOnceModal/);
    expect(panel).toMatch(/remainingActivationSeconds/);
    expect(panel).toMatch(/ttl_seconds: remaining/);
  });
});
