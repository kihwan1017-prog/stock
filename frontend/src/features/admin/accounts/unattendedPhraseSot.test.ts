import { describe, expect, it } from "vitest";

import { approvalPhraseForBroker } from "./accountLiveActivation";

/** Unattended confirmation vs LIVE approval — FE SoT 혼동 방지 */
const UNATTENDED_CONFIRM_ENABLE = "ENABLE 24H UNATTENDED";

describe("unattended phrase SoT", () => {
  it("UPBIT LIVE approval phrase is not the unattended confirmation", () => {
    const live = approvalPhraseForBroker("UPBIT");
    expect(live).toBe("ENABLE UPBIT LIVE TRADING");
    expect(live).not.toBe(UNATTENDED_CONFIRM_ENABLE);
  });

  it("KIWOOM LIVE phrase remains isolated", () => {
    expect(approvalPhraseForBroker("KIWOOM")).toBe(
      "ENABLE KIWOOM LIVE TRADING",
    );
  });
});
