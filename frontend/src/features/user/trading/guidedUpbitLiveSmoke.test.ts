import { describe, expect, it } from "vitest";

import {
  normalizeUpbitAccounts,
  pickDefaultUba,
} from "@/features/user/trading/guidedUpbitAccountHelpers";

describe("guided smoke account loading", () => {
  it("parses live-order accounts[] (not items)", () => {
    const rows = normalizeUpbitAccounts(
      {
        user_id: 1,
        accounts: [
          {
            user_broker_account_id: 1380,
            broker_code: "UPBIT",
            is_active: true,
            live_order_enabled: false,
            live_armed: false,
          },
          {
            user_broker_account_id: 99,
            broker_code: "KIWOOM",
            is_active: true,
          },
        ],
      },
      null,
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].user_broker_account_id).toBe(1380);
  });

  it("falls back to user accounts UPBIT list", () => {
    const rows = normalizeUpbitAccounts(
      { accounts: [] },
      {
        items: [
          {
            account_id: 1380,
            account_type: "UPBIT",
            is_active: true,
            is_default: true,
          },
        ],
      },
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].user_broker_account_id).toBe(1380);
  });

  it("auto-picks single or default account", () => {
    expect(
      pickDefaultUba([
        {
          user_broker_account_id: 1380,
          broker_code: "UPBIT",
          is_active: true,
        },
      ]),
    ).toBe(1380);
    expect(
      pickDefaultUba([
        {
          user_broker_account_id: 1,
          broker_code: "UPBIT",
          is_default: false,
        },
        {
          user_broker_account_id: 1380,
          broker_code: "UPBIT",
          is_default: true,
        },
      ]),
    ).toBe(1380);
  });

  it("exposes live order APIs", async () => {
    const mod = await import("@/features/user/api/userApi");
    expect(typeof mod.listMyLiveOrderStatus).toBe("function");
    expect(typeof mod.getLiveOrderPreflight).toBe("function");
    expect(typeof mod.postLiveOrderSmokeDispatch).toBe("function");
  });
});
