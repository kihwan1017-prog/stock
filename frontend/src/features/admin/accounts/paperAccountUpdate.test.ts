import { describe, expect, it } from "vitest";

import {
  buildPaperAccountUpdatePayload,
  canShowPaperAccountEditButton,
  initialCashDisabledReason,
  resolveCanEditInitialCash,
  validatePaperAccountUpdateForm,
} from "./paperAccountUpdate";

const base = {
  account_id: 1,
  account_name: "모의-A",
  initial_cash: 10_000_000,
  is_active: true,
  is_default: false,
  can_edit_initial_cash: true,
  has_trading_history: false,
};

describe("paperAccountUpdate helpers", () => {
  it("shows edit button only when write permission and valid id", () => {
    expect(canShowPaperAccountEditButton(true, 3)).toBe(true);
    expect(canShowPaperAccountEditButton(false, 3)).toBe(false);
    expect(canShowPaperAccountEditButton(true, 0)).toBe(false);
  });

  it("resolves initial cash editability from API flags", () => {
    expect(resolveCanEditInitialCash(base)).toBe(true);
    expect(
      resolveCanEditInitialCash({
        ...base,
        can_edit_initial_cash: false,
        has_trading_history: true,
      }),
    ).toBe(false);
    expect(initialCashDisabledReason(false)).toContain("초기 자산");
    expect(initialCashDisabledReason(true)).toBeNull();
  });

  it("builds PATCH payload with changed fields only", () => {
    const payload = buildPaperAccountUpdatePayload(base, {
      account_name: "모의-B",
      is_active: false,
      is_default: false,
      initial_cash: 10_000_000,
    });
    expect(payload).toEqual({
      account_name: "모의-B",
      is_active: false,
    });
  });

  it("omits initial_cash when trading history blocks edit", () => {
    const payload = buildPaperAccountUpdatePayload(
      {
        ...base,
        can_edit_initial_cash: false,
        has_trading_history: true,
      },
      {
        account_name: "모의-A",
        is_active: true,
        is_default: false,
        initial_cash: 1,
      },
    );
    expect(payload.initial_cash).toBeUndefined();
    expect(Object.keys(payload)).toHaveLength(0);
  });

  it("validates blank name and non-positive cash", () => {
    expect(
      validatePaperAccountUpdateForm({
        account_name: "   ",
        initial_cash: 100,
        canEditInitialCash: true,
      }),
    ).toContain("계좌명");
    expect(
      validatePaperAccountUpdateForm({
        account_name: "ok",
        initial_cash: 0,
        canEditInitialCash: true,
      }),
    ).toContain("초기 자산");
    expect(
      validatePaperAccountUpdateForm({
        account_name: "ok",
        initial_cash: 0,
        canEditInitialCash: false,
      }),
    ).toBeNull();
  });
});
