import { describe, expect, it } from "vitest";

import {
  formatLiveArm,
  formatOverallHealth,
  formatSlotStatus,
  formatWhyNoTradeReason,
} from "@/features/admin/ops-ux/userFacingStatus";

describe("userFacingStatus", () => {
  it("슬롯 상태를 운영자 언어로 바꾼다", () => {
    expect(formatSlotStatus("WAITING_SIGNAL").label).toBe("매수조건 감시 중");
    expect(formatSlotStatus("ENTRY_PENDING").label).toBe("매수 진행 중");
    expect(formatSlotStatus("EMPTY").label).toBe("후보 대기");
    expect(formatSlotStatus("OPEN").tone).toBe("success");
  });

  it("미거래 사유를 친화적으로 표현한다", () => {
    expect(formatWhyNoTradeReason("SIGNAL_EMIT_SUPPRESSED")).toBe(
      "중복 신호 대기 중",
    );
    expect(
      formatWhyNoTradeReason("Order amount exceeds configured limit"),
    ).toBe("주문 한도 때문에 대기");
  });

  it("전체 건강도와 LIVE/ARM을 표현한다", () => {
    expect(formatOverallHealth("GREEN").label).toBe("자동매매 정상");
    expect(formatLiveArm("ON", "ON")).toBe("자동매매 실행 가능");
    expect(formatLiveArm("OFF", "OFF")).toBe("자동매매 중지");
  });
});
