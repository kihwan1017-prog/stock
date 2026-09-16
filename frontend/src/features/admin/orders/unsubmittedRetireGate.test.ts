import { describe, expect, it } from "vitest";

import { canShowUnsubmittedRetireButton } from "./unsubmittedRetireGate";

describe("canShowUnsubmittedRetireButton", () => {
  it("shows for unsubmitted LIVE UPBIT PENDING", () => {
    expect(
      canShowUnsubmittedRetireButton({
        status_code: "PENDING",
        broker_order_id: null,
        submission_attempt_count: 0,
        user_broker_account_id: 1380,
        account_id: null,
        broker_code: "UPBIT",
      }),
    ).toBe(true);
  });

  it("hides when broker_order_id present", () => {
    expect(
      canShowUnsubmittedRetireButton({
        status_code: "PENDING",
        broker_order_id: "uuid",
        submission_attempt_count: 0,
        user_broker_account_id: 1380,
        account_id: null,
        broker_code: "UPBIT",
      }),
    ).toBe(false);
  });

  it("hides for paper account_id", () => {
    expect(
      canShowUnsubmittedRetireButton({
        status_code: "PENDING",
        broker_order_id: null,
        submission_attempt_count: 0,
        user_broker_account_id: null,
        account_id: 1,
        broker_code: "UPBIT",
      }),
    ).toBe(false);
  });
});
