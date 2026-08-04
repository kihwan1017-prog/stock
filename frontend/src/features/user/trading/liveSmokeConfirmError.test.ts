import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api/apiError";
import { formatLiveSmokeConfirmError } from "./liveSmokeConfirmError";

describe("formatLiveSmokeConfirmError", () => {
  it("renders risk rejection details (not network error)", () => {
    const err = new ApiError({
      status: 409,
      code: "RISK_ENGINE_BLOCKED",
      message: "Risk policy blocked this order.",
      details: {
        code: "RISK_ENGINE_BLOCKED",
        message: "Risk policy blocked this order.",
        detail: {
          error_code: "RISK_ENGINE_BLOCKED",
          message: "Risk policy blocked this order.",
          details: [
            "Projected investment ratio exceeds limit",
            "Daily loss limit reached",
            "Projected symbol position exceeds amount limit",
          ],
          order_submitted: false,
          create_order_calls: 0,
          broker_order_id: null,
        },
      },
    });
    const view = formatLiveSmokeConfirmError(err);
    expect(view.isRiskRejection).toBe(true);
    expect(view.title).toContain("Risk 정책");
    expect(view.detailLines).toContain("투자 비율 한도 초과");
    expect(view.detailLines).toContain("일일 손실 한도 도달");
    expect(view.detailLines).toContain("종목별 최대 보유금액 초과");
    expect(view.createOrderCalls).toBe(0);
    expect(view.orderSubmitted).toBe(false);
    expect(view.brokerOrderId).toBeNull();
  });

  it("does not treat generic errors as risk rejection", () => {
    const err = new ApiError({
      status: 400,
      code: "CONFIRMATION_TEXT_MISMATCH",
      message: "CONFIRMATION_TEXT_MISMATCH",
    });
    const view = formatLiveSmokeConfirmError(err);
    expect(view.isRiskRejection).toBe(false);
    expect(view.title).toBe("CONFIRMATION_TEXT_MISMATCH");
  });
});
