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

  it("unknown keeps raw code visible", () => {
    const r = entryBlockReasonKo("SOME_NEW_CODE");
    expect(r.known).toBe(false);
    expect(r.rawCode).toBe("SOME_NEW_CODE");
    expect(r.label).toBe("확인 필요 (SOME_NEW_CODE)");
  });
});

describe("slotStatusLabelKo", () => {
  it("uses operator-friendly labels", () => {
    expect(slotStatusLabelKo("WAITING_SIGNAL")).toBe("매수조건 감시 중");
    expect(slotStatusLabelKo("ENTRY_PENDING")).toContain("매수 주문");
    expect(slotStatusLabelKo("OPEN")).toContain("보유");
    expect(slotStatusLabelKo("EMPTY")).toContain("후보");
    expect(slotStatusLabelKo("COOLDOWN")).toContain("재진입");
    expect(unattendedLeaseLabelKo("PROTECTIVE_EXIT_ONLY")).toContain("보호");
  });
});

describe("tradingDisplayLabelsKo", () => {
  it("maps decisions and runtime values", async () => {
    const {
      decisionLabelKo,
      runtimeValueLabelKo,
      orderStatusLabelKo,
      formatKrwKo,
      brokerLabelKo,
      sideLabelKo,
      tradingKindLabelKo,
    } = await import("@/features/shared/display/tradingDisplayLabelsKo");
    expect(decisionLabelKo("ALLOW")).toBe("매수 허용");
    expect(decisionLabelKo("HOLD")).toBe("대기");
    expect(decisionLabelKo("REDUCE")).toBe("비중 축소");
    expect(decisionLabelKo("BLOCK")).toBe("차단");
    expect(decisionLabelKo("ZZZ_UNKNOWN")).toBe("확인 필요 (ZZZ_UNKNOWN)");
    expect(runtimeValueLabelKo("RUNNING")).toBe("실행 중");
    expect(runtimeValueLabelKo("READY_FOR_AUTO_TRADING")).toContain("준비");
    expect(runtimeValueLabelKo("WEIRD_STATE")).toBe("확인 필요 (WEIRD_STATE)");
    expect(orderStatusLabelKo("FILLED")).toBe("체결 완료");
    expect(orderStatusLabelKo("ACCEPTED")).toBe("주문 접수");
    expect(orderStatusLabelKo("PENDING")).toBe("처리 중");
    expect(orderStatusLabelKo("PARTIALLY_FILLED")).toBe("부분 체결");
    expect(orderStatusLabelKo("NOPE")).toBe("확인 필요 (NOPE)");
    expect(sideLabelKo("BUY")).toBe("매수");
    expect(sideLabelKo("SELL")).toBe("매도");
    expect(tradingKindLabelKo("AUTO")).toBe("자동매매");
    expect(tradingKindLabelKo("MANUAL")).toBe("수동매매");
    expect(formatKrwKo(10000)).toBe("10,000원");
    expect(brokerLabelKo("UPBIT")).toBe("업비트");
    expect(brokerLabelKo("KIWOOM")).toBe("키움증권");
  });

  it("ui labels include portfolio slots korean", async () => {
    const { UI_LABEL_KO } = await import(
      "@/features/shared/display/displayUiLabelsKo"
    );
    expect(UI_LABEL_KO.portfolioSlots).toBe("자동매매 후보 슬롯");
    expect(UI_LABEL_KO.runtime).toBe("자동매매 런타임");
    expect(UI_LABEL_KO.worker).toBe("주문 처리");
    expect(UI_LABEL_KO.killSwitch).toContain("Kill Switch");
    expect(UI_LABEL_KO.entryForwardValidation).toContain("Forward");
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
