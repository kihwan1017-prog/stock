import { describe, expect, it } from "vitest";

import { ONE_CLICK_PHRASES } from "@/features/admin/autotrading/upbitOneClick";
import { CONFIRM_ENABLE_24H_UNATTENDED } from "@/features/admin/accounts/upbit24x7Confirmations";

describe("upbit one-click phrases", () => {
  it("reuses unattended confirmation SoT", () => {
    expect(ONE_CLICK_PHRASES.CONFIRM_ENABLE_24H_UNATTENDED).toBe(
      CONFIRM_ENABLE_24H_UNATTENDED,
    );
    expect(ONE_CLICK_PHRASES.CONFIRM_ENABLE_24H_UNATTENDED).toBe(
      "ENABLE 24H UNATTENDED",
    );
  });
});
