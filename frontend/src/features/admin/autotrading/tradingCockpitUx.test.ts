import { describe, expect, it } from "vitest";

import {
  ENTRY_BLOCK_REASON_KO,
  entryBlockReasonKo,
  entryBlockReasonShortKo,
} from "@/features/admin/autotrading/entryBlockReasonKo";
import {
  orderTradingKindMatchesFilter,
  resolveOrderTradingKind,
} from "@/features/admin/autotrading/orderOwnership";
import {
  slotStatusLabelKo,
  unattendedLeaseLabelKo,
} from "@/features/admin/autotrading/slotStatusLabels";
import {
  ownershipLabelKo,
  ownershipMatchesHoldingsFilter,
} from "@/features/admin/accounts/symbolOwnershipLabels";
import {
  ORDER_LIST_TAB_LABELS,
  orderMatchesTab,
} from "@/features/admin/orders/orderListTabs";
import { adminMenuItems, flattenMenuItems, userMenuItems } from "@/config/menu";

describe("entryBlockReasonKo", () => {
  it("maps known codes", () => {
    expect(entryBlockReasonShortKo("SHORT_MA_NOT_ABOVE_LONG_MA")).toContain(
      "단기",
    );
    expect(entryBlockReasonKo("RSI_TOO_HIGH").known).toBe(true);
    expect(Object.keys(ENTRY_BLOCK_REASON_KO).length).toBeGreaterThanOrEqual(11);
  });

  it("unknown keeps raw in tooltip fields", () => {
    const r = entryBlockReasonKo("SOME_NEW_CODE");
    expect(r.known).toBe(false);
    expect(r.rawCode).toBe("SOME_NEW_CODE");
    expect(r.label).toContain("확인할 수 없습니다");
  });
});

describe("slotStatusLabelKo", () => {
  it("uses operator-friendly labels", () => {
    expect(slotStatusLabelKo("WAITING_SIGNAL")).toBe("매수조건 감시 중");
    expect(slotStatusLabelKo("ENTRY_PENDING")).toContain("매수 주문");
    expect(slotStatusLabelKo("OPEN")).toContain("보유");
    expect(slotStatusLabelKo("EMPTY")).toContain("후보");
    expect(unattendedLeaseLabelKo("PROTECTIVE_EXIT_ONLY")).toContain("보호");
  });
});

describe("ownership filters", () => {
  it("hides FREE on ALL holdings filter", () => {
    expect(ownershipMatchesHoldingsFilter("FREE", "ALL")).toBe(false);
    expect(ownershipMatchesHoldingsFilter("MANUAL", "ALL")).toBe(true);
    expect(ownershipMatchesHoldingsFilter("AUTO", "AUTO")).toBe(true);
    expect(ownershipLabelKo("AUTO_EXCLUDED")).toBe("자동매매 제외");
  });
});

describe("order ownership provenance", () => {
  it("prefers strategy_id over null-only heuristics", () => {
    expect(resolveOrderTradingKind({ strategy_id: 1 }).kind).toBe("AUTO");
    expect(resolveOrderTradingKind({ strategy_code: "UPBIT_FM" }).kind).toBe(
      "AUTO",
    );
    expect(
      resolveOrderTradingKind({ execution_mode: "MANUAL" }).kind,
    ).toBe("MANUAL");
    expect(
      orderTradingKindMatchesFilter(
        resolveOrderTradingKind({ strategy_code: "X" }),
        "AUTO",
      ),
    ).toBe(true);
  });
});

describe("order list tabs", () => {
  it("filters by tab", () => {
    expect(orderMatchesTab("SUBMITTED", 0, "open")).toBe(true);
    expect(orderMatchesTab("FILLED", 1, "fills")).toBe(true);
    expect(orderMatchesTab("CANCELLED", 0, "rejected")).toBe(true);
    expect(orderMatchesTab("FILLED", 1, "all")).toBe(true);
    expect(ORDER_LIST_TAB_LABELS.open).toBe("진행 주문");
  });
});

describe("single admin menu", () => {
  it("has cockpit leaves and no USER/member entries", () => {
    const flat = flattenMenuItems(adminMenuItems);
    const keys = flat.map((i) => i.key);
    expect(keys).toContain("dashboard");
    expect(keys).toContain("autotrading-upbit");
    expect(keys).toContain("autotrading-kiwoom");
    expect(keys).toContain("orders");
    expect(keys).not.toContain("members");
    expect(keys).not.toContain("roles");
    expect(keys).not.toContain("profile");
    expect(userMenuItems).toEqual([]);
  });
});
