import { describe, expect, it } from "vitest";

import {
  buildPaperAccountDeleteConfirmContent,
  canShowPaperAccountDeleteButton,
} from "./paperAccountDelete";

describe("paperAccountDelete helpers", () => {
  it("builds soft-delete confirm copy with account id and name", () => {
    const text = buildPaperAccountDeleteConfirmContent({
      account_id: 42,
      account_name: "모의-A",
      is_default: false,
    });
    expect(text).toContain("모의-A");
    expect(text).toContain("42");
    expect(text).toContain("Soft Delete");
    expect(text).toContain("Hard Delete");
    expect(text).not.toContain("기본 계좌입니다");
  });

  it("mentions default account when is_default", () => {
    const text = buildPaperAccountDeleteConfirmContent({
      account_id: 1,
      account_name: "default",
      is_default: true,
    });
    expect(text).toContain("기본 계좌입니다");
  });

  it("shows delete button only for admin with valid id", () => {
    expect(canShowPaperAccountDeleteButton(true, 7)).toBe(true);
    expect(canShowPaperAccountDeleteButton(false, 7)).toBe(false);
    expect(canShowPaperAccountDeleteButton(true, 0)).toBe(false);
    expect(canShowPaperAccountDeleteButton(true, null)).toBe(false);
  });
});
