import { describe, expect, it } from "vitest";

import { approvalPhraseForBroker } from "./accountLiveActivation";
import {
  APPROVAL_ENABLE_UPBIT_LIVE,
  CONFIRM_ENABLE_24H_UNATTENDED,
} from "./upbit24x7Confirmations";

/**
 * Unattended lease ACK vs LIVE ON phrase — 역할 분리 SoT.
 * Unattended Enable은 LIVE phrase를 받지 않는다.
 */
describe("unattended approval model SoT", () => {
  it("keeps LIVE ON phrase distinct from unattended confirmation", () => {
    const live = approvalPhraseForBroker("UPBIT");
    expect(live).toBe(APPROVAL_ENABLE_UPBIT_LIVE);
    expect(live).toBe("ENABLE UPBIT LIVE TRADING");
    expect(CONFIRM_ENABLE_24H_UNATTENDED).toBe("ENABLE 24H UNATTENDED");
    expect(live).not.toBe(CONFIRM_ENABLE_24H_UNATTENDED);
  });

  it("KIWOOM LIVE phrase remains isolated", () => {
    expect(approvalPhraseForBroker("KIWOOM")).toBe(
      "ENABLE KIWOOM LIVE TRADING",
    );
  });
});
