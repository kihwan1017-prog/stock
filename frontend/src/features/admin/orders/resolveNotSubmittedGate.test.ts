import { describe, expect, it } from "vitest";

import {
  canShowResolveNotSubmittedButton,
  outboxStatusForOrder,
} from "./resolveNotSubmittedGate";

describe("resolveNotSubmittedGate", () => {
  const base = {
    status_code: "PENDING",
    broker_order_id: null,
    submission_attempt_count: 0,
    user_broker_account_id: 1380,
    account_id: null,
    broker_code: "UPBIT",
  };

  it("shows for AMBIGUOUS outbox", () => {
    expect(canShowResolveNotSubmittedButton(base, "AMBIGUOUS")).toBe(true);
  });

  it("hides for PENDING outbox", () => {
    expect(canShowResolveNotSubmittedButton(base, "PENDING")).toBe(false);
  });

  it("hides when broker uuid present", () => {
    expect(
      canShowResolveNotSubmittedButton(
        { ...base, broker_order_id: "uuid" },
        "AMBIGUOUS",
      ),
    ).toBe(false);
  });

  it("maps outbox status for order", () => {
    expect(
      outboxStatusForOrder(1684, [
        { order_id: 1684, event_type: "SUBMIT_ORDER", status_code: "AMBIGUOUS" },
      ]),
    ).toBe("AMBIGUOUS");
  });
});
